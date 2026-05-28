"""Thin Gemini 3 helper shared by the sub-agents.

Kept tiny on purpose: ADK wires the agents (see loop_agent.py); the sub-agent
*logic* just needs structured Gemini calls, so we isolate them here for testability.
"""

from __future__ import annotations

import json
from typing import TypeVar

from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)


def _client() -> genai.Client:
    s = get_settings()
    if s.google_genai_use_vertexai:
        return genai.Client(
            vertexai=True,
            project=s.google_cloud_project,
            location=s.google_cloud_location,
        )
    return genai.Client(
        vertexai=False,
        api_key=s.gemini_api_key,
    )


def _openai_client() -> AsyncOpenAI:
    s = get_settings()
    if s.is_openai:
        return AsyncOpenAI(api_key=s.openai_api_key)
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=s.gemini_api_key,
        default_headers={
            "HTTP-Referer": "https://github.com/SirjanSingh/cassandra",
            "X-Title": "Cassandra",
        },
    )


async def structured(prompt: str, schema: type[T], *, system: str = "") -> T:
    """Ask Gemini 3 / OpenRouter / OpenAI for a response that parses into `schema` (Pydantic)."""
    s = get_settings()
    if s.is_openai or s.is_openrouter:
        client = _openai_client()
        model = s.openai_model if s.is_openai else s.gemini_model
        sys_instr = (system + "\n\nIMPORTANT: Be extremely concise. Respond with minimal reasoning/text to fit within token limits.") if system else "IMPORTANT: Be extremely concise. Respond with minimal reasoning/text to fit within token limits."
        resp = await client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": sys_instr},
                {"role": "user", "content": prompt},
            ],
            response_format=schema,
            temperature=0.2,
        )
        parsed = resp.choices[0].message.parsed
        if parsed is None:
            raise ValueError("Failed to parse response from OpenAI/OpenRouter model")
        return parsed

    resp = await _client().aio.models.generate_content(
        model=s.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system or None,
            response_mime_type="application/json",
            response_schema=schema.model_json_schema(),
            temperature=0.2,
        ),
    )
    return schema.model_validate(json.loads(resp.text))


async def text(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
    s = get_settings()
    if s.is_openai or s.is_openrouter:
        client = _openai_client()
        model = s.openai_model if s.is_openai else s.gemini_model
        sys_instr = (system + "\n\nIMPORTANT: Be extremely concise. Respond with minimal reasoning/text to fit within token limits.") if system else "IMPORTANT: Be extremely concise. Respond with minimal reasoning/text to fit within token limits."
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_instr},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""

    resp = await _client().aio.models.generate_content(
        model=s.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system or None, temperature=temperature
        ),
    )
    return resp.text or ""
