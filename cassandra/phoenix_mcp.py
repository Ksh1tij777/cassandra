"""The single gateway to Arize Phoenix via its MCP server (NFR-10).

This is the ONLY module that talks MCP. Every Phoenix tool family Cassandra needs
(spans, annotations, datasets, experiments, prompts - REQUIREMENTS.md S4) is exposed
as a typed async method here. If the Day-1 enumeration spike reveals different tool
names or argument schemas, this file is the only thing that changes.

SPIKE-RECONCILE: the tool names in `_TOOLS` and the argument shapes below are the
*intended* surface from ARCHITECTURE.md S4. `scripts/spike_enumerate_mcp.py` prints
the *actual* surface; reconcile before Phase 2 feature work.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import Settings, get_settings
from .models import DatasetExample, SpanRecord

# Intended Phoenix MCP tool names. Confirm/replace via the spike.
_TOOLS = {
    "list_projects": "list-projects",
    "query_spans": "get-spans",
    "annotate_span": "add-span-annotation",
    "create_dataset": "create-dataset",
    "add_examples": "add-dataset-examples",
    "create_experiment": "create-experiment",
    "run_experiment": "run-experiment",
    "get_experiment": "get-experiment-results",
    "create_prompt_version": "create-prompt-version",
    "get_prompt": "get-prompt",
}


class PhoenixMCP:
    """Async wrapper around a stdio MCP session to @arizeai/phoenix-mcp."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        self._session: ClientSession | None = None

    @asynccontextmanager
    async def session(self):
        """Open a stdio MCP session. Phoenix creds passed via env to the server."""
        params = StdioServerParameters(
            command=self.s.phoenix_mcp_command,
            args=self.s.phoenix_mcp_arg_list,
            env={
                "PHOENIX_API_KEY": self.s.phoenix_api_key,
                "PHOENIX_BASE_URL": self.s.phoenix_base_url,
            },
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self._session = session
                try:
                    yield self
                finally:
                    self._session = None

    async def _call(self, tool_key: str, **arguments: Any) -> Any:
        if self._session is None:
            raise RuntimeError("PhoenixMCP used outside `async with .session()`")
        tool_name = _TOOLS[tool_key]
        result = await self._session.call_tool(tool_name, arguments=arguments)
        return _unwrap(result)

    # --- introspection (used by the spike + Watcher project resolution) ---

    async def list_tools(self) -> list[dict]:
        if self._session is None:
            raise RuntimeError("PhoenixMCP used outside `async with .session()`")
        tools = await self._session.list_tools()
        return [
            {"name": t.name, "description": t.description, "schema": t.inputSchema}
            for t in tools.tools
        ]

    async def list_projects(self) -> list[dict]:
        return _as_list(await self._call("list_projects"))

    # --- Watcher (FR-W2) ---

    async def query_spans(
        self, project: str, since: datetime | None, limit: int = 50
    ) -> list[SpanRecord]:
        raw = await self._call(
            "query_spans",
            project_name=project,
            start_time=since.isoformat() if since else None,
            limit=limit,
        )
        return [normalize_span(r, project) for r in _as_list(raw)]

    # --- Diagnostician (FR-D3) ---

    async def annotate_span(
        self, span_id: str, label: str, score: float, explanation: str
    ) -> str:
        res = await self._call(
            "annotate_span",
            span_id=span_id,
            annotation_name="cassandra",
            label=label,
            score=score,
            explanation=explanation,
        )
        return _id_of(res, fallback=f"ann-{span_id}")

    # --- Synthesizer (FR-S2) ---

    async def create_dataset(self, name: str, description: str) -> str:
        res = await self._call("create_dataset", name=name, description=description)
        return _id_of(res, fallback=name)

    async def add_examples(self, dataset_id: str, examples: list[DatasetExample]) -> int:
        rows = [
            {
                "input": {"question": e.input_text},
                "output": {"expected": e.expected_answer},
                "metadata": {"acceptance": e.acceptance_criterion},
            }
            for e in examples
        ]
        await self._call("add_examples", dataset_id=dataset_id, examples=rows)
        return len(rows)

    # --- Evaluator (FR-E1/E3/E4) ---

    async def create_experiment(self, dataset_id: str, name: str, prompt: str) -> str:
        res = await self._call(
            "create_experiment", dataset_id=dataset_id, name=name, prompt=prompt
        )
        return _id_of(res, fallback=name)

    async def run_experiment(self, experiment_id: str) -> dict:
        return _as_dict(await self._call("run_experiment", experiment_id=experiment_id))

    async def get_experiment(self, experiment_id: str) -> dict:
        return _as_dict(await self._call("get_experiment", experiment_id=experiment_id))

    # --- Patcher (FR-PA2) ---

    async def create_prompt_version(
        self, name: str, prompt_text: str, metadata: dict
    ) -> str:
        res = await self._call(
            "create_prompt_version",
            name=name,
            template=prompt_text,
            metadata=metadata,
        )
        return _id_of(res, fallback=f"{name}-v?")

    def span_url(self, span: SpanRecord) -> str:
        """Deep link into the Phoenix UI for the dashboard (FR-DB4)."""
        return f"{self.s.phoenix_base_url}/projects/{span.project}/spans/{span.span_id}"


# --- normalization & unwrap helpers (the only schema-coupled code) ---


def normalize_span(raw: dict, project: str) -> SpanRecord:
    """Map a raw Phoenix MCP span dict to our SpanRecord.

    SPIKE-RECONCILE: adjust key paths to the real schema dumped by the spike.
    """
    attrs = raw.get("attributes", raw)
    return SpanRecord(
        span_id=str(raw.get("span_id") or raw.get("context", {}).get("span_id", "")),
        trace_id=str(raw.get("trace_id") or raw.get("context", {}).get("trace_id", "")),
        project=project,
        started_at=_parse_dt(raw.get("start_time")),
        input_text=_deep_str(attrs, ("input", "value"), ("llm", "input_messages")),
        output_text=_deep_str(attrs, ("output", "value"), ("llm", "output_messages")),
        tool_calls=raw.get("tool_calls", []),
        raw=raw,
    )


def _unwrap(result: Any) -> Any:
    """MCP tool results arrive as content blocks; pull out JSON/text payload."""
    content = getattr(result, "content", result)
    if isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
    return content


def _as_list(v: Any) -> list:
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        for key in ("data", "results", "items", "spans", "projects"):
            if isinstance(v.get(key), list):
                return v[key]
    return [v] if v else []


def _as_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {"value": v}


def _id_of(v: Any, fallback: str) -> str:
    if isinstance(v, dict):
        for key in ("id", "dataset_id", "experiment_id", "annotation_id", "version_id"):
            if v.get(key):
                return str(v[key])
    return str(v) if isinstance(v, (str, int)) else fallback


def _parse_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now()


def _deep_str(d: dict, *paths: tuple[str, ...]) -> str:
    for path in paths:
        cur: Any = d
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and cur:
            return cur if isinstance(cur, str) else json.dumps(cur)[:4000]
    return ""
