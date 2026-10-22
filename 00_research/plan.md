# Plan: Tiered-Access AI Research Platform Prototype

## TL;DR
Build a prototype platform (codename: **Dalal** -- Tiered Compute Platform) with FastAPI backend, Streamlit frontend, SQLite DB, and Claude-powered LLM agent. Users authenticate with username/password and are assigned one of three access tiers (Open, Controlled, Restricted) that gate data visibility and tool access. Three-agent anomaly detection pipeline (Christy, Admin Collector, Pirot) monitors researcher behavior against declared interests and published work.

---

## Architecture Overview

```
Streamlit UI  ->  FastAPI Backend  ->  SQLite (users, sessions, audit log)
                      |
               Claude LLM Agent (Anthropic API)
                      |
               Data Layer (docs, DB, APIs -- mocked for prototype)
                      |
               Agent Pipeline:
                 Christy (ORCID profiles)
                   -> Admin Collector (activity logging)
                     -> Pirot (anomaly detection)
```

---

## Phase 1: Project Scaffolding & User Management [COMPLETE]

**Goal**: Runnable app with auth and tiered user system.

1. **Project structure** (*no dependencies*)
   - `backend/` -- FastAPI app
   - `frontend/` -- Streamlit app
   - `00_research/` -- planning docs, architecture notes
   - `docker-compose.yml`, `.env.example`, `README.md`

2. **Backend: User model & auth** (*no dependencies*)
   - SQLite via SQLAlchemy (async with aiosqlite)
   - User table: `id, username, orcid_id, hashed_password, tier, research_interest, is_active, created_at`
   - Password hashing with `bcrypt` directly (not passlib)
   - JWT auth tokens via `python-jose`
   - ORCID iD validation (regex `^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$`, unique constraint)
   - Endpoints: `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
   - `require_tier()` dependency for role-based access control

3. **Backend: Admin user management** (*depends on 2*)
   - `GET /admin/users` -- list users (restricted tier only)
   - `POST /admin/users` -- create user with tier/ORCID/interest (restricted only)
   - `PATCH /admin/users/{id}` -- update tier/active/interest (restricted only)
   - `POST /admin/users/{id}/reset-password`, `POST /admin/users/delete` -- bulk ops
   - Seed script: admin + 25 research users with simulated query histories

4. **Frontend: Auth & user management UI** (*depends on 2, 3*)
   - Login page with session state management
   - Admin panel (restricted tier only): create users, manage tiers, bulk delete
   - Sidebar showing current user and tier badge

## Phase 2: LLM Agent Integration [COMPLETE]

**Goal**: Working Claude agent with tier-aware data/tool access.

5. **Backend: Claude agent service** (*parallel with 3-4*)
   - Anthropic Python SDK integration (Messages API with tool-use agentic loop)
   - `AgentService` class with conversation history persisted to SQLite
   - `ConversationMessage` model for history persistence
   - System prompt templating based on user tier

6. **Backend: Tier-gated tools & data** (*depends on 5*)
   - Tool registry pattern: `register_tool(name, handler, min_tier)`
   - 6 tools across 3 tiers:
     - **Open**: `search_public_docs`, `get_platform_info`
     - **Controlled**: + `query_research_data`, `analyze_dataset`
     - **Restricted**: + `list_platform_users`, `get_usage_stats`
   - Agentic loop: Claude calls tools iteratively until response complete

7. **Backend: Chat endpoints** (*depends on 5, 6*)
   - `POST /chat` -- send message, returns response with tool calls
   - `GET /chat/history` -- retrieve conversation history
   - `POST /chat/reset` -- clear conversation
   - Inline Admin Collector: records every query to `query_history`

8. **Frontend: Chat UI** (*depends on 7*)
   - Streamlit chat interface with message history
   - Tool call visualization (expandable tool use details)

## Phase 3: Three-Agent Pipeline [COMPLETE]

**Goal**: Detect researchers whose platform activity diverges from their stated interests and published work.

9. **Backend: Admin Collector agent** (*depends on 7*)
   - `record_query()` -- stores query text, tools invoked, response summary
   - `record_data_access()` -- stores dataset name, tier, access type
   - `DataAccessLog` and `QueryHistory` models
   - Wired inline into `chat.py` router (called after every chat response)

10. **Backend: Christy agent -- ORCID profile builder** (*depends on 2*)
    - Fetch publications from ORCID public API (`pub.orcid.org/v3.0/{orcid}/works`)
    - Extract titles; store in `OrcidPublication` table
    - Build frequency-based keyword topic summary; store in `OrcidProfile` table
    - Cache with 30-day TTL; refresh on demand or batch
    - Router endpoints:
      - `POST /admin/christy/fetch/{user_id}` -- fetch/refresh single user
      - `POST /admin/christy/fetch-all` -- batch refresh
      - `GET /admin/christy/profile/{user_id}` -- view profile + publications
      - `GET /admin/christy/status` -- cache freshness stats

11. **Backend: Pirot scoring engine** (*depends on 9, 10*)
    - Recall-based keyword overlap with simple stemming (prototype; designed for swap to sentence-transformers)
    - Two-check scan:
      - Check 1: query keywords vs declared `research_interest` keywords
      - Check 2: query keywords vs ORCID publication/profile keywords (via Christy)
    - Divergence logic: if no ORCID data, interest check alone can flag
    - `WarningSeverity` enum (low/medium/high), `WarningStatus` enum (pending/reviewed/dismissed)
    - `UserWarning` model with severity, detail JSON, review tracking
    - Configurable thresholds: `INTEREST_THRESHOLD=0.15`, `MIN_QUERIES_FOR_SCAN=5`

12. **Backend: Pirot API endpoints** (*depends on 11*)
    - `POST /admin/pirot/scan` -- trigger scan for one or all users (restricted)
    - `GET /admin/pirot/warnings` -- list warnings with filters (status, severity, user_id)
    - `PATCH /admin/pirot/warnings/{id}` -- mark reviewed/dismissed
    - `GET /admin/pirot/user/{id}/profile` -- research profile + live divergence scores
    - `GET /admin/pirot/user/{id}/queries` -- query history for review

13. **Backend: Seed data** (*depends on 9-12*)
    - 25 users with real ORCID iDs from published vaccine/immunology researchers
    - 5 super users (restricted, 25-40 queries): viral vector, mRNA, structural, delivery, subunit scientists
    - 5 irregular users (open, 1-3 queries): infrequent platform visitors
    - 15 average users (controlled, 8-18 queries): 13 legitimate + 2 mismatched
    - 2 mismatched users: t_chen (astrophysics), l_martinez (marine biology) -- 85% off-topic queries
    - User-specific queries for niche researchers to reduce false positives
    - Research interest overlap: each user overlaps with at least 3 others across 7 topic clusters

## Phase 4: Audit & Usage Tracking [PARTIAL]

**Goal**: Foundation for monitoring and cost tracking.

14. **Backend: Audit logging** (*parallel with Phase 2-3*)
    - `AuditLog` table: `id, user_id, action, detail_json, timestamp` -- created, not fully wired
    - `LLMUsage` table: `id, user_id, model, input_tokens, output_tokens, cost_estimate, timestamp` -- created, not fully wired
    - Middleware auto-logging not yet implemented

15. **Backend: Usage tracking** (*depends on 14*)
    - `GET /admin/usage` -- not yet implemented
    - Per-request token tracking from Claude API -- not yet wired

16. **Frontend: Usage dashboard** (*depends on 15*)
    - `frontend/pages/usage.py` -- not yet created

## Phase 5: Frontend Enhancements [NOT STARTED]

**Goal**: Complete admin experience for the agent pipeline.

17. **Frontend: Warnings dashboard** (*depends on 12*)
    - Admin-only page listing flagged accounts with severity badges
    - Per-user detail view: stated interest, ORCID pubs, query history, divergence scores
    - Review workflow: dismiss, escalate, or restrict
    - File: `frontend/pages/warnings.py`

18. **Frontend: Research interest field** (*depends on 10*)
    - Add research_interest to registration form
    - Show/edit in admin user detail panel

## Phase 6: Containerization [PARTIAL]

19. **Docker setup** (*depends on all above*)
    - `Dockerfile` for backend (FastAPI + uvicorn) -- exists, not tested
    - `Dockerfile` for frontend (Streamlit) -- exists, not tested
    - `docker-compose.yml` orchestrating both + volume for SQLite -- exists, not tested
    - `.env.example` with `ANTHROPIC_API_KEY`, `JWT_SECRET`, etc. -- exists

---

## Relevant Files

### Backend Core
- `backend/app/main.py` -- FastAPI app entry, CORS, router includes
- `backend/app/models.py` -- All SQLAlchemy models (User, AuditLog, LLMUsage, ConversationMessage, OrcidPublication, OrcidProfile, DataAccessLog, QueryHistory, UserWarning)
- `backend/app/schemas.py` -- Pydantic request/response schemas
- `backend/app/auth.py` -- JWT auth, bcrypt password hashing, `require_tier()` dependency
- `backend/app/database.py` -- async SQLAlchemy + aiosqlite setup
- `backend/app/config.py` -- settings from env vars
- `backend/seed.py` -- admin + 25 research users with simulated queries

### Backend Routers
- `backend/app/routers/auth.py` -- register, login, me
- `backend/app/routers/admin.py` -- user CRUD (restricted tier)
- `backend/app/routers/chat.py` -- chat endpoints + inline Admin Collector
- `backend/app/routers/christy.py` -- ORCID profile admin endpoints
- `backend/app/routers/pirot.py` -- anomaly scan/warnings/profile endpoints

### Backend Services
- `backend/app/services/agent.py` -- Claude AgentService with tool-use loop
- `backend/app/services/tools.py` -- tier-gated tool registry (6 tools)
- `backend/app/services/agents/christy.py` -- ORCID fetch, topic summary, caching
- `backend/app/services/agents/pirot.py` -- keyword scoring, stemming, scan logic
- `backend/app/services/agents/admin_collector.py` -- query/access logging

### Frontend
- `frontend/app.py` -- Streamlit main app, login, sidebar
- `frontend/pages/admin.py` -- admin user management panel
- `frontend/pages/chat.py` -- chat interface with tool visualization

### Agent Plans
- `agents/pirot/plan.md` -- Pirot anomaly detection design
- `agents/christy/plan.md` -- Christy ORCID profile builder design
- `agents/admin_collector/plan.md` -- Admin Collector design

### Infrastructure
- `docker-compose.yml`, `.env.example`, `.gitignore`, `README.md`

---

## Verification

1. **Auth flow**: Register user -> login -> get JWT -> access protected endpoint -> confirm tier-based access control
2. **Tier enforcement**: Create users at each tier -> verify Open cannot access Controlled/Restricted data/tools
3. **Chat**: Send message as each tier -> verify agent responds and only uses tier-appropriate tools
4. **Pirot scan**: Run `POST /admin/pirot/scan` -> verify t_chen and l_martinez flagged; 23 others pass
5. **Christy fetch**: Run `POST /admin/christy/fetch/{id}` -> verify ORCID publications retrieved and cached
6. **Warning review**: Flag user -> PATCH to reviewed -> verify filter by status works
7. **Docker**: `docker compose up` -> access Streamlit at localhost:8501, API at localhost:8000/docs
8. **Admin**: Restricted user can create/modify users; Open/Controlled users get 403

---

## Decisions

| Decision | Rationale |
|----------|-----------|
| SQLite | Prototype simplicity; migrate to PostgreSQL for production |
| JWT tokens (not sessions) | Stateless API auth for API-first architecture |
| Anthropic Claude | Sole LLM provider; abstract behind service interface for future multi-model |
| `bcrypt` directly (not passlib) | passlib unmaintained, incompatible with bcrypt 5.x |
| Recall-based keyword scoring | Prototype scorer; designed for swap to sentence-transformer embeddings |
| Simple suffix stemmer | Avoids NLTK/spaCy dependency; handles morphological variants (immunity/immune) |
| MIN_QUERIES_FOR_SCAN=5 | Skips irregular users with too few queries for meaningful analysis |
| No OAuth/SSO | Prototype scope; add later |
| Separate venvs for backend/frontend | Different dependency trees; avoids conflicts |

## Future Considerations (Post-Prototype)

1. **Sentence-transformer embeddings**: Replace keyword scoring in Pirot with cosine similarity on embedded vectors for higher accuracy
2. **Admin Tracking Agent**: Autonomous agent monitoring user creation patterns, privilege escalation, and account anomalies
3. **LLM Usage Monitor Agent**: Cost spikes, unusual query patterns, prompt injection detection
4. **Nefarious Use Detection**: Fine-tuned classifier on chat logs for social engineering, data exfiltration, policy violations
5. **Audit middleware**: Wire AuditLog/LLMUsage tables into request lifecycle for complete activity tracking
4. **Multi-agent orchestration**: Pirot + Admin Collector + future agents coordinated via a shared event bus
