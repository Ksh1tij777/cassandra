"""Shared domain models that thread through the supervision pipeline.

The `Incident` object is the single piece of state passed Watcher -> Patcher
(ARCHITECTURE.md S2). Each sub-agent enriches it and passes it on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FailureClass(str, Enum):
    HALLUCINATION = "hallucination"
    PROMPT_DRIFT = "prompt_drift"
    TOOL_FAILURE = "tool_failure"
    OK = "ok"


class SpanRecord(BaseModel):
    """A normalized view of a Phoenix span tree (root LLM span + child tool spans).

    SPIKE-RECONCILE: field mapping depends on the exact Phoenix MCP span schema;
    `phoenix_mcp.normalize_span` is the only place that needs to change.
    """

    span_id: str
    trace_id: str
    project: str
    started_at: datetime
    input_text: str = ""
    output_text: str = ""
    tool_calls: list[dict] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


class Verdict(BaseModel):
    """Diagnostician output (FR-D1, FR-D2)."""

    failure_class: FailureClass
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    expected_behavior: str = ""

    @property
    def is_failure(self) -> bool:
        return self.failure_class is not FailureClass.OK


class DatasetExample(BaseModel):
    """One synthesized adversarial probe (FR-S1)."""

    input_text: str
    expected_answer: str
    acceptance_criterion: str


class ExperimentResult(BaseModel):
    """Evaluator output (FR-E4)."""

    experiment_id: str
    baseline_pass_rate: float
    candidate_pass_rate: float | None = None

    @property
    def delta(self) -> float | None:
        if self.candidate_pass_rate is None:
            return None
        return round(self.candidate_pass_rate - self.baseline_pass_rate, 4)


class Stage(str, Enum):
    WATCHED = "watched"
    DIAGNOSED = "diagnosed"
    SYNTHESIZED = "synthesized"
    EVALUATED = "evaluated"
    PATCHED = "patched"


class Incident(BaseModel):
    """Threads through the whole pipeline. Identity = offending span_id (FR-L3 dedupe)."""

    incident_id: str
    span: SpanRecord
    created_at: datetime = Field(default_factory=_now)
    stage: Stage = Stage.WATCHED

    verdict: Verdict | None = None
    annotation_id: str | None = None
    dataset_id: str | None = None
    dataset_examples: list[DatasetExample] = Field(default_factory=list)
    experiment: ExperimentResult | None = None
    candidate_prompt: str | None = None
    candidate_prompt_version: str | None = None
    prompt_diff: str | None = None

    @classmethod
    def from_span(cls, span: SpanRecord) -> "Incident":
        return cls(incident_id=f"inc-{span.span_id}", span=span)


class PipelineEvent(BaseModel):
    """Streamed to the dashboard SSE feed (FR-DB1, FR-L2)."""

    incident_id: str
    stage: Stage
    at: datetime = Field(default_factory=_now)
    title: str
    detail: str = ""
    phoenix_url: str | None = None
    payload: dict = Field(default_factory=dict)
