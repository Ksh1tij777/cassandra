# Cassandra — The Meta-Agent That Watches Other Agents

> An AI agent that babysits other AI agents. Cassandra watches production agents through
> Arize Phoenix traces, catches hallucinations, prompt drift, and tool-call failures in
> real time, auto-synthesizes evaluation datasets from the failing traces, runs
> LLM-as-judge evaluations, and proposes A/B-ready prompt patches — all from inside Phoenix.

**Hackathon:** Google Cloud Rapid Agent Hackathon — *Building Agents for Real-World Challenges*
**Partner track:** Arize (Phoenix — LLM observability & evaluation)
**Submission deadline:** 2026-06-12 02:30 IST (= 2026-06-11 14:00 PDT) · internal ship target 2026-06-11
**Verified against the official Devpost page on 2026-05-17** (6,582 participants, $60k total)

---

## The Problem

Every team running LLM agents in production has the same unsolved problem: **agents fail
silently.** A customer-facing agent confidently invents a refund policy. A prompt drifts
after a model upgrade. A tool call fails and the agent hallucinates around the gap.

Today this is caught by **humans staring at dashboards**, sampling traces by hand, writing
eval datasets manually, and editing prompts on intuition. It does not scale, it is slow,
and most failures are never caught at all.

## The Idea

Cassandra closes that loop autonomously. It is, recursively, **an agent whose job is to
supervise other agents.** It runs the exact workflow Phoenix was built for — but
automated, continuous, and self-improving:

```
 monitor ─▶ diagnose ─▶ synthesize evals ─▶ run experiment ─▶ propose patch ─▶ (loop)
```

## Why This Wins the Arize Bucket

- **Quality of the Idea (25%)** — A beautifully recursive concept: an agent that audits
  agents. Almost every other entry will *be* an agent; almost none will be an agent
  *about* agents. Memorable and original.
- **Technological Implementation (25%)** — Exercises nearly the entire Phoenix MCP tool
  surface: traces, spans, annotations, datasets, experiments, prompt management. Arize
  judges are Phoenix engineers; this is non-trivial, deep, on-product usage.
- **Potential Impact (25%)** — Every production LLM team has this exact pain and currently
  solves it with eyeballs.
- **Design (25%)** — A live dashboard where a failure is caught, annotated, turned into a
  dataset, and patched — visibly, in seconds, on camera.

See [docs/WINNING_STRATEGY.md](docs/WINNING_STRATEGY.md) for the full judging-criteria map.

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/PRD.md](docs/PRD.md) | Product Requirements Document — vision, users, scope, success metrics |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Detailed functional & non-functional requirements |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System & agent architecture, data flow, MCP surface |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | 25-day solo build plan with checkpoints |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | Shot-by-shot ≤3-minute video script |
| [docs/WINNING_STRATEGY.md](docs/WINNING_STRATEGY.md) | Competitive read & judging-criteria mapping |

## Tech Stack

- **Reasoning core:** Gemini 3 (or direct OpenAI `gpt-4o-mini` / `gpt-4o` integration)
- **Orchestration:** Google Cloud Agent Builder (the officially named build path) —
  `LoopAgent` + `SequentialAgent` via ADK/Agent Engine as the underlying runtime
- **Runtime:** Vertex AI Agent Engine
- **Partner MCP (required):** Arize Phoenix MCP server (`@arizeai/phoenix-mcp`)
- **Scheduling:** Cloud Functions (trace poller)
- **UI / hosting:** Cloud Run (dashboard)
- **Secrets:** Secret Manager
- **Optional:** BigQuery (long-term span analytics)

## Repository Layout

```
cassandra/
├── patient/              # C1 — the fragile "ShopBot" victim agent
│   ├── agent.py          #   Gemini-3 / OpenAI agent + FastAPI /chat + OpenInference spans
│   ├── tools.py          #   intentionally flaky get_refund_policy / lookup_order
│   └── instrumentation.py#   OTLP exporter → Phoenix patient-prod
├── cassandra/            # C3 — the meta-agent
│   ├── models.py         #   Incident object threaded through the pipeline
│   ├── phoenix_mcp.py    #   the single Phoenix MCP gateway (NFR-10)
│   ├── llm.py            #   Gemini 3 / OpenAI structured/text helper
│   ├── watcher.py        #   FR-W: poll spans since durable cursor
│   ├── diagnostician.py  #   FR-D: LLM-as-judge → annotate Phoenix span
│   ├── synthesizer.py    #   FR-S: adversarial dataset → Phoenix dataset
│   ├── evaluator.py      #   FR-E: baseline vs candidate Phoenix experiment
│   ├── patcher.py        #   FR-PA: prompt patch → Phoenix prompt version
│   ├── loop_agent.py     #   pipeline + thin ADK LoopAgent shell
│   ├── state.py          #   durable cursor + dedupe (Firestore/local)
│   └── events.py         #   in-process bus → dashboard SSE
├── dashboard/            # C4 — FastAPI: serves web/dist + SSE /events + /ask
├── web/                  # React + Vite + Tailwind + Framer Motion cockpit
│   ├── src/components/   #   Hero, Manifesto, Cockpit, EventCard, views, …
│   └── public/img/       #   license-clear photography (Picsum/Unsplash)
├── scripts/
│   ├── run_pipeline.py   #   runs one complete end-to-end supervision cycle locally
│   ├── seed_incident.py  #   C5 — deterministic demo trap + labeled set
│   └── spike_enumerate_mcp.py  # Day-1 Phoenix MCP enumeration (de-risk R1)
├── deploy/               # cloudrun.Dockerfile, cloudbuild.yaml, agent_engine.py
├── tests/                # offline unit tests (LLM + MCP mocked)
└── docs/                 # PRD, requirements, architecture, plan, demo, strategy
```

## Run Locally

```bash
pip install -e ".[dev]"
cp .env.example .env            # Fill in OpenAI/Gemini API keys + Phoenix URLs

# 1. build the React cockpit (served by the dashboard)
cd web && npm install && npm run build && cd ..

# 2. Start the Patient Agent (ShopBot)
uvicorn patient.agent:app --port 8082 --reload

# 3. Start the FastAPI Dashboard
uvicorn dashboard.main:app --port 8085 --reload

# 4. Drive one supervision cycle (Seeding an incident, polling, and auto-patching)
python scripts/run_pipeline.py

# Run offline unit tests
pytest
```

> **Frontend dev with hot reload:** `cd web && npm run dev` (Vite dev server starts on :5173, proxying `/events` and `/ask` requests to the FastAPI dashboard running on :8085).

## Status

**Codebase complete and fully verified.**
All modules byte-compile and live end-to-end integration runs succeed.

| Area | State |
|------|-------|
| Docs (PRD → strategy) | ✅ complete, reconciled with official Devpost page |
| Patient + incident seeder (C1/C5) | ✅ code complete and verified live |
| Cassandra 5 sub-agents + loop (C3) | ✅ code complete and verified live |
| Dashboard (C4) | ✅ code complete — SSE + UI |
| Deploy manifests (Cloud Run / Agent Engine) | ✅ written |
| Phoenix MCP surface | ✅ fully integrated and verified via live `@arizeai/phoenix-mcp` |
| Live end-to-end run on Phoenix | ✅ verified live (both Gemini and OpenAI backends) |
| Feedback loop protection | ✅ verified live (test session filtering prevents infinite loops) |
| Hosted URL + demo video | ⛔ pending |

## License

Apache-2.0 — see [LICENSE](LICENSE).
