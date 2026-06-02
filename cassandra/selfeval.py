"""Self-evaluation: Cassandra grading its OWN diagnostic accuracy.

The Arize track awards bonus points to agents that "use their own observability data
to improve over time." This closes that loop literally: the meta-agent runs the
labeled trap library through the live Patient, asks its own Diagnostician to judge each
turn, and scores the verdicts against ground truth (cassandra/traps.py) — producing a
diagnostic-accuracy Scorecard. The watcher, now watching itself.

All Patient calls use session_id="test" so the Watcher filters them out (no self-
supervision loop) and the judge runs WITHOUT Phoenix annotation side effects.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

import httpx

from .config import get_settings
from .diagnostician import Diagnostician
from .models import Scorecard, ScorecardCase
from .traps import LABELED_TRAPS, LabeledTrap


class SelfEvaluator:
    def __init__(self, diagnostician: Diagnostician | None = None) -> None:
        self.s = get_settings()
        self.diag = diagnostician or Diagnostician()

    async def _patient_reply(self, c: httpx.AsyncClient, message: str) -> str:
        r = await c.post(
            self.s.patient_endpoint,
            json={"message": message, "session_id": "test"},
        )
        r.raise_for_status()
        return r.json().get("reply", "")

    async def _grade(self, c: httpx.AsyncClient, trap: LabeledTrap) -> ScorecardCase:
        output = await self._patient_reply(c, trap.message)
        verdict = await self.diag.judge(trap.message, output)
        predicted = verdict.failure_class.value
        return ScorecardCase(
            message=trap.message,
            expected=trap.expected_label,
            predicted=predicted,
            confidence=verdict.confidence,
            correct=(predicted == trap.expected_label),
        )

    async def evaluate(self, traps: list[LabeledTrap] | None = None) -> Scorecard:
        traps = traps or LABELED_TRAPS
        async with httpx.AsyncClient(timeout=60) as c:
            cases = await asyncio.gather(*(self._grade(c, t) for t in traps))

        per_class: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
        for case in cases:
            bucket = per_class[case.expected]
            bucket["total"] += 1
            bucket["correct"] += int(case.correct)

        return Scorecard(
            total=len(cases),
            correct=sum(1 for c in cases if c.correct),
            per_class=dict(per_class),
            cases=list(cases),
        )
