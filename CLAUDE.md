# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

TCP (Tiered Compute Platform) — a prototype where users get one of three access tiers (Open / Controlled / Restricted), talk to a Claude-powered agent whose tools are gated by tier, and where a set of background "agents" profile users and flag anomalous research behavior. FastAPI backend + Streamlit frontend + SQLite. No package.json; this is a Python project.

## Required configuration

There is **one** secret you must supply to use the full app: `ANTHROPIC_API_KEY` in `.env` (repo root). It powers the chat agent only. Get it from https://console.anthropic.com/ → Settings → API Keys.

- Without it, everything works **except** `POST /api/v1/chat`, which returns `503 "ANTHROPIC_API_KEY is not configured"` (see `backend/app/routers/chat.py`). Auth, admin, the Detector/Profiler/Clusterer agents, and the dashboard do not need it.
- `JWT_SECRET` also lives in `.env`; any random string works for local dev (generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`).
- No other external service needs a key. The Profiler agent calls the **ORCID public API** (`https://pub.orcid.org/v3.0`) which is keyless.
- `.env` is gitignored. Copy `.env.example` → `.env` to start.

## Running locally

```bash
# Backend (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python seed.py                       # creates SQLite tcp.db with seeded users
uvicorn app.main:app --reload        # http://localhost:8000  (Swagger at /docs)

# Frontend (terminal 2)
cd frontend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py                 # http://localhost:8501
```

`uvicorn` must be launched from inside `backend/` — imports are rooted at `app.*` and the default DB path resolves to `backend/tcp.db`. The frontend hardcodes the backend URL as `API_BASE = "http://localhost:8000/api/v1"` in `frontend/app.py`.

Docker alternative: `cp .env.example .env && docker compose up --build` (API :8000, UI :8501). Note: `docker-compose.yml` does **not** run `seed.py`, so a Docker DB starts empty.

### Login credentials

`seed.py` **hardcodes** passwords (it ignores `ADMIN_PASSWORD` from `.env`, despite what `.env.example` and the README imply):
- admin / **`1234`** (restricted tier)
- all 25 seeded research users / **`test1234`**

The README's "admin / admin" is stale.

## Architecture

### Tier model (the core concept)
`Tier` is an enum `open < controlled < restricted` (`backend/app/models.py`). It gates two independent things:
1. **Agent tools** — `backend/app/services/tools.py` holds a singleton `ToolRegistry`. Each tool declares a `min_tier`; `tools_for_tier()` returns only tools at or below the user's level. `AgentService` (`services/agent.py`) runs the Anthropic agentic loop: send message → if `stop_reason == "tool_use"` run the handler and feed results back → repeat until done. System prompt is chosen per tier. All current tool handlers return **mock data** — there's no real dataset behind `query_dataset` etc.
2. **API routes** — admin/agent routers depend on `get_current_user` (`backend/app/auth.py`, JWT + bcrypt) and check tier; restricted-only endpoints live under `/admin/*`.

### The four "agents"
"Agent" here means two different things — don't conflate them:
- **The chat agent** (`services/agent.py` + `services/tools.py`) — the live Claude conversation, the only thing that uses the API key.
- **Background analysis agents** under `backend/app/services/agents/`, each with a thin router under `backend/app/routers/` and a planning doc under `agents/<name>/plan.md`:
  - **logger** (`agents/logger.py`) — not a router; called inline from `chat.py` to log every query into `QueryHistory` and dataset accesses into `DataAccessLog`. This is the data source the others analyze.
  - **detector** (`/admin/detector/*`) — scans query history for behavior anomalies (off-topic mismatch, topic drift, collusion) and writes `UserWarning` rows; supports listing/triaging warnings.
  - **profiler** (`/admin/profiler/*`) — fetches each user's publications from the ORCID public API into `OrcidPublication`/`OrcidProfile` to build a research profile (used as the "expected topic" baseline).
  - **clusterer** (`/admin/clusterer/*`) — an offline-style ML pipeline (`services/agents/clusterer/pipeline.py`: feature engineering → persona model → anomaly detection → reporting, scikit-learn + pandas). `/analyze/save` writes CSV/JSON artifacts to `backend/output/clusterer/`.

### Request flow for chat
`frontend/pages/chat.py` → `POST /api/v1/chat` (`routers/chat.py`) → loads `ConversationMessage` history for the user → `AgentService.chat(messages, tier)` → persists user+assistant messages, `LLMUsage` token counts, and (via logger) `QueryHistory` + `DataAccessLog` → returns reply + tool-call trace.

### Data layer
Async SQLAlchemy 2.0 over `aiosqlite`. `init_db()` (in `lifespan`) calls `Base.metadata.create_all` — **there are no migrations**; schema changes require dropping `backend/tcp.db` and re-seeding. All models in `backend/app/models.py`: `User`, `AuditLog`, `LLMUsage`, `ConversationMessage`, `OrcidPublication`, `OrcidProfile`, `DataAccessLog`, `QueryHistory`, `UserWarning`.

### Seed data is deliberately structured
`seed.py` (random seed 42, reproducible) plants known anomalies the Detector agent is meant to catch: 2 "mismatched" users (~85% off-topic queries), 2 "drift" users (ramping off-topic in week 2), and 1 "collusion" pair (k_corbett + n_pardi issuing 20 identical sensitive queries in a 2–3 AM burst on 2026-05-28). When changing anomaly-detection logic, validate against these ground-truth scenarios.

## Conventions

- No test suite, linter config, or build step exists in the repo. Verify changes by running the app and exercising endpoints (`/docs` is the fastest way).
- Adding a chat tool: register it in `services/tools.py` with a `min_tier`; the registry and agentic loop pick it up automatically.
- Adding a background agent: follow `agents/README.md` — create `agents/<name>/plan.md`, implement under `services/agents/<name>.py`, wire a router and `include_router` in `main.py`.
- CORS is wide open (`allow_origins=["*"]`) and JWT defaults are weak — fine for the prototype, flagged for production in code comments.
