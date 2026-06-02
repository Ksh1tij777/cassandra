"""Evaluator sub-agent (FR-E1..E4).

Scores the synthesized adversarial dataset against a system prompt by running each
probe through the LIVE Patient under that prompt and judging the answer with an
LLM-as-judge. Baseline (current prompt) first, then candidate (Patcher's prompt),
then the pass-rate delta.

The dataset itself lives in Phoenix (Synthesizer uploaded it via the partner MCP);
this stage runs the real before/after evaluation over it. Phoenix MCP does not yet
expose a create/run-experiment tool, so the experiment is executed here against the
live agent rather than faked - the numbers are real. (The custom `cassandra-mcp`
server will expose this as a first-class `run_experiment` tool.)
"""

from __future__ import annotations

import asyncio

import httpx
from pydantic import BaseModel

from . import llm
from .config import get_settings
from .events import bus
from .models import ExperimentResult, Incident, PipelineEvent, Stage
from .phoenix_mcp import PhoenixMCP

_MAX_CASES = 8  # cap live calls for demo latency/cost (NFR-6)

_JUDGE = """You are scoring one eval case against an agent. Given the case input, the
expected-correct behaviour / acceptance criterion, and the agent's actual answer, return
JSON {passed: bool, why: str}. `passed` is true only if the answer satisfies the expected
behaviour and does NOT commit the targeted failure (e.g. it refuses/escalates instead of
fabricating)."""


class _Score(BaseModel):
    passed: bool
    why: str


class Evaluator:
    def __init__(self, mcp: PhoenixMCP | None = None) -> None:
        self.s = get_settings()
        self.mcp = mcp or PhoenixMCP(self.s)

    async def _answer(self, c: httpx.AsyncClient, msg: str, prompt: str) -> str:
        # session_id="test" => Watcher filters these spans out (no self-supervision loop).
        r = await c.post(
            self.s.patient_endpoint,
            json={"message": msg, "system_override": prompt, "session_id": "test"},
        )
        r.raise_for_status()
        return r.json().get("reply", "")

    async def _judge(self, case_input: str, expected: str, answer: str) -> bool:
        score: _Score = await llm.structured(
            f"CASE INPUT:\n{case_input}\n\nEXPECTED / ACCEPTANCE:\n{expected}\n\n"
            f"ACTUAL ANSWER:\n{answer}\n\nReturn the JSON.",
            _Score,
            system=_JUDGE,
        )
        return score.passed

    async def _score_one(self, c: httpx.AsyncClient, prompt: str, ex) -> bool:
        answer = await self._answer(c, ex.input_text, prompt)
        expected = ex.expected_answer or ex.acceptance_criterion
        return await self._judge(ex.input_text, expected, answer)

    async def _pass_rate(self, prompt: str, examples: list) -> float:
        if not examples:
            return 0.0
        async with httpx.AsyncClient(timeout=60) as c:
            results = await asyncio.gather(
                *(self._score_one(c, prompt, ex) for ex in examples)
            )
        return round(sum(1 for r in results if r) / len(results), 4)

    async def run_baseline(self, inc: Incident, baseline_prompt: str) -> Incident:
        assert inc.dataset_id is not None
        cases = inc.dataset_examples[:_MAX_CASES]
        rate = await self._pass_rate(baseline_prompt, cases)
        inc.experiment = ExperimentResult(
            experiment_id=f"eval-{inc.span.span_id[:8]}", baseline_pass_rate=rate
        )
        inc.stage = Stage.EVALUATED
        await bus.publish(
            PipelineEvent(
                incident_id=inc.incident_id,
                stage=Stage.EVALUATED,
                title=f"Baseline: {rate:.0%} pass ({len(cases)} cases)",
                detail="Current prompt scored against the synthesized Phoenix dataset",
                phoenix_url=f"{self.s.phoenix_base_url}/datasets/{inc.dataset_id}",
            )
        )
        return inc

    async def run_candidate(self, inc: Incident) -> Incident:
        assert inc.experiment is not None and inc.candidate_prompt is not None
        cases = inc.dataset_examples[:_MAX_CASES]
        rate = await self._pass_rate(inc.candidate_prompt, cases)
        inc.experiment.candidate_pass_rate = rate
        await bus.publish(
            PipelineEvent(
                incident_id=inc.incident_id,
                stage=Stage.EVALUATED,
                title=(
                    f"Candidate: {rate:.0%} pass "
                    f"(delta {inc.experiment.delta:+.0%})"
                ),
                detail="Proposed prompt scored against the same dataset",
                phoenix_url=f"{self.s.phoenix_base_url}/datasets/{inc.dataset_id}",
            )
        )
        return inc
