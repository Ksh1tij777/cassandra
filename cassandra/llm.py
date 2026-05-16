"""Thin Gemini 3 helper shared by the sub-agents.

Kept tiny on purpose: ADK wires the agents (see loop_agent.py); the sub-agent
*logic* just needs structured Gemini calls, so we isolate them here for testability.
"""

from __future__ import annotations

import json
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)


def _client() -> genai.Client:
    s = get_settings()
    return genai.Client(
        vertexai=s.google_genai_use_vertexai,
        project=s.google_cloud_project,
        location=s.google_cloud_location,
    )


async def structured(prompt: str, schema: type[T], *, system: str = "") -> T:
    """Ask Gemini 3 for a response that parses into `schema` (Pydantic)."""
    s = get_settings()
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
    resp = await _client().aio.models.generate_content(
        model=s.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system or None, temperature=temperature
        ),
    )
    return resp.text or ""
