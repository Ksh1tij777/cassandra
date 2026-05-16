"""Dashboard service (FR-DB1..DB5).

Serves the single-page UI, streams pipeline events over SSE, and proxies the
"send customer message" box to the Patient so the whole loop is driveable live
on camera.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from cassandra.config import get_settings
from cassandra.events import bus

app = FastAPI(title="Cassandra Dashboard")
_UI = (Path(__file__).parent / "ui" / "index.html").read_text(encoding="utf-8")


class Ask(BaseModel):
    message: str


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _UI


@app.get("/events")
async def events():
    async def gen():
        async for ev in bus.subscribe():
            yield {"event": "pipeline", "data": json.dumps(ev.model_dump(mode="json"))}

    return EventSourceResponse(gen())


@app.post("/ask")
async def ask(req: Ask) -> dict:
    """Drive the demo: send a customer message to the Patient (FR-DB3)."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(s.patient_endpoint, json={"message": req.message})
        r.raise_for_status()
        return r.json()


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "service": "dashboard"}
