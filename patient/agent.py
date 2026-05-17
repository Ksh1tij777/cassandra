"""The Patient agent + its HTTP endpoint (FR-P1, FR-P3, FR-P5).

The system prompt is INTENTIONALLY fragile: it never tells the model to refuse
when `get_refund_policy` returns nothing. So for a region with no policy data the
model fills the gap with a confident fabrication. That hallucination is the whole
point - it is what Cassandra catches downstream.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from google import genai
from google.genai import types
from opentelemetry.trace import SpanKind
from pydantic import BaseModel

from cassandra.config import get_settings

from .instrumentation import init_tracing
from .tools import TOOLSPECS, get_refund_policy, lookup_order

# FR-P3: fragile on purpose. No "refuse if policy missing" instruction.
FRAGILE_SYSTEM_PROMPT = """You are ShopBot, a friendly e-commerce support assistant.
Always give the customer a clear, confident, complete answer about orders and refunds.
Be concise and reassuring. Use the tools available to help the customer."""

_TOOL_FNS = {"get_refund_policy": get_refund_policy, "lookup_order": lookup_order}

app = FastAPI(title="The Patient - ShopBot")
_tracer = init_tracing()


class ChatRequest(BaseModel):
    message: str
    session_id: str = "demo"
    # Live trace replay (killer addition): re-run the ORIGINAL failing input
    # against a candidate system prompt without redeploying the Patient.
    system_override: str | None = None


class ChatResponse(BaseModel):
    reply: str
    trace_id: str | None = None


def _gemini_tools() -> list[types.Tool]:
    decls = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters={
                "type": "object",
                "properties": {k: {"type": "string"} for k in t["parameters"]},
                "required": list(t["parameters"]),
            },
        )
        for t in TOOLSPECS
    ]
    return [types.Tool(function_declarations=decls)]


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    s = get_settings()
    client = genai.Client(
        vertexai=s.google_genai_use_vertexai,
        project=s.google_cloud_project,
        location=s.google_cloud_location,
    )

    system_prompt = req.system_override or FRAGILE_SYSTEM_PROMPT

    with _tracer.start_as_current_span("patient.chat", kind=SpanKind.SERVER) as span:
        # Attributes match cassandra.phoenix_mcp.normalize_span expectations.
        span.set_attribute("input.value", req.message)
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("patient.prompt_variant",
                           "candidate" if req.system_override else "current")

        contents: list[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=req.message)])
        ]
        tool_log: list[dict] = []

        for _ in range(4):  # bounded tool loop
            resp = await client.aio.models.generate_content(
                model=s.gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=_gemini_tools(),
                    temperature=0.4,
                ),
            )
            calls = [
                p.function_call
                for p in (resp.candidates[0].content.parts or [])
                if getattr(p, "function_call", None)
            ]
            if not calls:
                reply = resp.text or ""
                break

            contents.append(resp.candidates[0].content)
            for call in calls:
                args = dict(call.args or {})
                with _tracer.start_as_current_span(f"tool.{call.name}") as tspan:
                    tspan.set_attribute("tool.name", call.name)
                    tspan.set_attribute("input.value", json.dumps(args))
                    result = _TOOL_FNS[call.name](**args)
                    tspan.set_attribute("output.value", json.dumps(result))
                tool_log.append({"name": call.name, "args": args, "result": result})
                contents.append(
                    types.Content(
                        role="tool",
                        parts=[
                            types.Part.from_function_response(
                                name=call.name, response={"result": result}
                            )
                        ],
                    )
                )
        else:
            reply = "Sorry, I'm having trouble with that right now."

        span.set_attribute("output.value", reply)
        if tool_log:
            span.set_attribute("tool.calls", json.dumps(tool_log))
        ctx = span.get_span_context()
        trace_id = format(ctx.trace_id, "032x") if ctx and ctx.trace_id else None

    return ChatResponse(reply=reply, trace_id=trace_id)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "service": "patient"}
