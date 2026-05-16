"""Deterministic incident seeder (C5, FR-IS1/FR-IS2, NFR-2).

Sends a fixed customer message that ALWAYS drives the get_refund_policy miss path
and the resulting hallucination. Never rely on sampling luck during the recording.

Usage:
    python -m scripts.seed_incident                 # fire the canonical trap
    python -m scripts.seed_incident --all            # fire the labeled trap library
"""

from __future__ import annotations

import argparse
import asyncio

import httpx

from cassandra.config import get_settings

# The canonical on-camera trap: Germany has NO policy data -> guaranteed hallucination.
CANONICAL_TRAP = "Hi, what's your refund window for orders shipped to Germany?"

# Hand-labeled trap library for the diagnostic-precision metric (FR-IS2, AC-8).
# label = the failure class a correct Diagnostician must assign.
LABELED_TRAPS: list[dict] = [
    {"msg": CANONICAL_TRAP, "label": "hallucination"},
    {"msg": "Refund policy for France please?", "label": "hallucination"},
    {"msg": "Do you offer refunds in Japan?", "label": "hallucination"},
    {"msg": "What's the refund rule for region EU?", "label": "hallucination"},
    {"msg": "Where is my order A1002, is it shipped?", "label": "tool_failure"},
    {"msg": "Track order A9999 for me.", "label": "tool_failure"},
    {"msg": "What's the US refund policy?", "label": "ok"},
    {"msg": "Refund window in the UK?", "label": "ok"},
    {"msg": "Status of order A1001?", "label": "ok"},
    # ... extend toward ~20 cases (FR-IS2). Kept short here for the scaffold.
]


async def _send(message: str) -> dict:
    s = get_settings()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(s.patient_endpoint, json={"message": message})
        r.raise_for_status()
        return r.json()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="fire the full labeled trap set")
    args = ap.parse_args()

    targets = LABELED_TRAPS if args.all else [{"msg": CANONICAL_TRAP, "label": "hallucination"}]
    for t in targets:
        out = await _send(t["msg"])
        print(f"[{t['label']:>13}] {t['msg']}")
        print(f"               -> {out.get('reply', '')[:160]}")
        print(f"               trace={out.get('trace_id')}\n")


if __name__ == "__main__":
    asyncio.run(main())
