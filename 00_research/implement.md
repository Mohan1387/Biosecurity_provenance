# TCP Implementation Log

## Phase 1: Project Scaffolding & User Management

**Status**: Complete

### What was built

**Backend (FastAPI + SQLite)**
- Async SQLAlchemy with aiosqlite for database
- User model with `id, username, orcid_id, hashed_password, tier, research_interest, is_active, created_at`
- AuditLog and LLMUsage models (tables created, not yet wired to middleware)
- JWT auth via `python-jose`, password hashing via `bcrypt` directly
- ORCID iD validation (regex + unique constraint)
- Auth endpoints: `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- Admin endpoints (restricted tier only):
  - `GET /admin/users` -- list all users
  - `POST /admin/users` -- create user with tier/ORCID/research_interest
  - `PATCH /admin/users/{id}` -- update tier/active/interest
  - `POST /admin/users/{id}/reset-password` -- reset any user's password
  - `POST /admin/users/delete` -- bulk delete users (protects admin account)
- CORS middleware allowing all origins (prototype only)
- Health check at `GET /health`

**Frontend (Streamlit)**
- Login/register page with session state management
- Sidebar showing current user and tier badge
- Home page with feature cards (Chat, Usage, Admin)
- Admin panel (restricted tier only):
  - Create new user form (username, password, tier)
  - User list with expandable details (tier, active toggle, save)
  - Password reset per user
  - Checkbox selection + bulk delete button
  - Admin account protected from deletion in UI and backend

**Infrastructure**
- `docker-compose.yml` with backend + frontend services
- Dockerfiles for both services
- `.env.example` with all config vars
- `.gitignore` for Python artifacts, DB files, .env
- `README.md` with quickstart (local + Docker)

### Decisions made

| Decision | Rationale |
|----------|-----------|
| `bcrypt` directly instead of `passlib` | `passlib` is unmaintained and incompatible with bcrypt 5.x |
| `greenlet` added as explicit dependency | Required by async SQLAlchemy but not auto-installed |
| `--reload-exclude '.venv'` for uvicorn | WatchFiles was detecting .venv file syncs (OneDrive) causing infinite reload loops |
| Admin user permanently seeded as `admin`/`1234` | Seed script always resets password on re-run; account protected from deletion |
| Separate venvs for backend and frontend | Different dependency trees; avoids conflicts |
| JWT (stateless) over sessions | Simpler for API-first architecture; frontend stores token in session state |
| SQLite for prototype | File-based, zero config; plan to migrate to PostgreSQL for production |

### Issues encountered

1. **`passlib` + `bcrypt` 5.x incompatibility** -- `passlib` tried to access `bcrypt.__about__.__version__` which no longer exists. Switched to using `bcrypt` directly.
2. **Missing `greenlet`** -- async SQLAlchemy requires greenlet but it wasn't installed automatically. Added to requirements.txt.
3. **Uvicorn reload spam** -- OneDrive file syncing caused WatchFiles to detect changes in `.venv/` site-packages, triggering hundreds of server reloads. Fixed with `--reload-exclude '.venv'`.
4. **Port 8000 zombies** -- Killed uvicorn processes left orphan listeners on port 8000. Used `lsof -ti:8000 | xargs kill -9` to clean up.

### Files created

```
backend/
  app/__init__.py
  app/main.py
  app/config.py
  app/database.py
  app/models.py
  app/schemas.py
  app/auth.py
  app/routers/__init__.py
  app/routers/auth.py
  app/routers/admin.py
  seed.py
  requirements.txt
  Dockerfile
  .venv/

frontend/
  app.py
  pages/admin.py
  requirements.txt
  Dockerfile
  .venv/

docker-compose.yml
.env.example
.gitignore
README.md
00_research/plan.md
```

---

## Phase 2: LLM Agent Integration

**Status**: Complete

### What was built

**Claude Agent Service**
- `AgentService` class wrapping Anthropic Messages API with full tool-use agentic loop
- Conversation history persisted to SQLite via `ConversationMessage` model
- System prompt dynamically templated based on user tier (open/controlled/restricted)
- Iterative tool execution: Claude calls tools, results fed back, loop continues until final text response

**Tier-Gated Tool Registry**
- `register_tool(name, handler, min_tier)` pattern with automatic tier filtering
- 6 tools across 3 tiers:
  - **Open**: `search_public_docs`, `get_platform_info`
  - **Controlled**: + `query_research_data`, `analyze_dataset`
  - **Restricted**: + `list_platform_users`, `get_usage_stats`
- Mock data sources (sample docs, mock API responses, sample DB tables)

**Chat Endpoints**
- `POST /api/v1/chat` -- send message, returns response with tool call details
- `GET /api/v1/chat/history` -- retrieve conversation history for current user
- `POST /api/v1/chat/reset` -- clear conversation history

**Chat UI**
- Streamlit chat interface with full message history display
- Expandable tool call visualization showing tool name, input, and output

### Files created/modified

```
backend/
  app/services/__init__.py
  app/services/agent.py      -- AgentService with Claude tool-use loop
  app/services/tools.py      -- tier-gated tool registry (6 tools)
  app/routers/chat.py        -- chat endpoints
  app/models.py              -- added ConversationMessage model

frontend/
  pages/chat.py              -- chat interface with tool visualization
```

### Issues encountered

1. **Anthropic SDK tool-use loop** -- Required iterating until Claude returns a non-tool-use response; implemented as while loop checking `stop_reason`.

---

## Phase 3: Three-Agent Pipeline

**Status**: Complete

### What was built

**Admin Collector Agent** (`backend/app/services/agents/admin_collector.py`)
- `record_query(db, user_id, query_text, tools_invoked, response_summary)` -- stores every chat interaction
- `record_data_access(db, user_id, dataset_name, dataset_tier, access_type)` -- stores data access events
- New models: `DataAccessLog` (user_id, dataset_name, dataset_tier, access_type, timestamp), `QueryHistory` (user_id, query_text, tools_invoked, response_summary, timestamp)
- Wired inline into `chat.py` router -- called automatically after every chat response

**Christy Agent -- ORCID Profile Builder** (`backend/app/services/agents/christy.py`)
- `fetch_orcid_works(orcid_id)` -- async HTTP client calling ORCID public API v3.0
- `build_topic_summary(publications)` -- frequency-based keyword extraction from publication titles
- `build_profile_for_user(db, user, force=False)` -- orchestrates fetch, store, summarize with 30-day TTL cache
- `build_all_profiles(db, force=False)` -- batch refresh for all users with ORCID iDs
- `get_cache_status(db)` -- aggregate freshness statistics
- New models: `OrcidPublication` (user_id, orcid_id, put_code, title, journal, pub_year, pub_type, external_url), `OrcidProfile` (user_id, topic_summary, pub_count, last_refreshed)
- Router endpoints (`backend/app/routers/christy.py`):
  - `POST /admin/christy/fetch/{user_id}` -- fetch/refresh single user
  - `POST /admin/christy/fetch-all` -- batch refresh all users
  - `GET /admin/christy/profile/{user_id}` -- view profile + publications
  - `GET /admin/christy/status` -- cache freshness stats

**Pirot Agent -- Anomaly Detection** (`backend/app/services/agents/pirot.py`)
- `_simple_stem(word)` -- aggressive suffix-stripping stemmer for keyword normalization
- `_extract_keywords(text)` -- tokenization + stopword removal + stemming
- `_keyword_overlap_score(query_kw, reference_kw)` -- recall-based metric: fraction of reference keywords found in query corpus
- `_determine_severity(interest_score, pub_score)` -- maps divergence to low/medium/high
- `scan_user(db, user)` -- two-check scan with smart null-data handling:
  - Check 1: query keywords vs declared research_interest
  - Check 2: query keywords vs ORCID profile/publications (if available)
  - If no ORCID data, interest check alone can flag
- `scan_all_users(db)` -- batch scan all active non-admin users
- `get_user_profile_report(db, user)` -- combined profile with live divergence scores
- New models: `WarningSeverity` enum (low/medium/high), `WarningStatus` enum (pending/reviewed/dismissed), `UserWarning` (user_id, warning_type, severity, detail JSON, status, reviewed_by, reviewed_at)
- Router endpoints (`backend/app/routers/pirot.py`):
  - `POST /admin/pirot/scan` -- trigger scan for one or all users
  - `GET /admin/pirot/warnings` -- list with filters (status_filter, severity, user_id)
  - `PATCH /admin/pirot/warnings/{id}` -- mark reviewed/dismissed (tracks reviewer)
  - `GET /admin/pirot/user/{id}/profile` -- research profile + live scores
  - `GET /admin/pirot/user/{id}/queries` -- query history for manual review

**Seed Data** (`backend/seed.py`)
- 25 users + admin with real ORCID iDs from published vaccine/immunology researchers
- Breakdown: 5 super (restricted, 25-40 queries), 5 irregular (open, 1-3 queries), 15 average (controlled, 8-18 queries)
- 2 mismatched users among the average group:
  - `t_chen` -- astrophysics researcher (ORCID 0000-0002-5765-3026), 85% off-topic queries
  - `l_martinez` -- marine biologist (ORCID 0000-0001-7599-3363), 85% off-topic queries
- 30 vaccine-domain queries + 15 mismatched queries in the pool
- User-specific queries for niche researchers (d_burton, s_crotty, h_virgin, n_pardi, g_nabel, m_moore, a_sette, l_corey, d_kaslow, r_rappuoli) to prevent false positives
- 7 research overlap clusters: mRNA/LNP, structural/bnAbs, clinical/correlates, computational/epitopes, mucosal/innate, influenza/pandemic, viral vectors

### Scoring decisions

| Decision | Rationale |
|----------|-----------|
| Recall-based scoring (not Jaccard) | Short interest strings vs long query corpora; Jaccard denominator swamps numerator |
| Simple suffix stemmer | Handles immunity/immune, vaccination/vaccine without NLTK/spaCy dependency |
| Null ORCID = no pass | When only interest data available, interest check alone can flag; prevents neutral pass on missing data |
| MIN_QUERIES_FOR_SCAN=5 | Irregular users (1-3 queries) produce meaningless scores; skip them |
| INTEREST_THRESHOLD=0.15 | Tuned so legitimate vaccine researchers score 0.25-1.0 while mismatched score 0.0-0.125 |
| User-specific queries in seed | Generic vaccine query pool doesn't contain niche keywords (e.g., "germinal center"); prevents false positives |

### Issues encountered

1. **SQLite naive datetime bug** -- `last_refreshed` from SQLite comes back as naive datetime; fixed by checking `.tzinfo is None` and replacing with UTC before TTL comparison.
2. **Weighted Jaccard dominated by query volume** -- Original scoring used `2 * overlap / (sum_a + sum_b)` which gave near-zero scores for everyone because query corpora have hundreds of keywords vs 8-10 in interest string. Switched to recall: `|interest ∩ queries| / |interest|`.
3. **Stemming false positives** -- Without stemming, "immunity" (interest) didn't match "immune" (queries), causing legitimate vaccine researchers to be flagged. Added aggressive suffix-stripping stemmer.
4. **Neutral pass on missing ORCID** -- Original logic gave `publication_score=0.5` when no ORCID data existed, letting mismatched users pass via the OR gate. Fixed to track `has_pub_data` and allow interest-only flagging.

### Files created/modified

```
backend/
  app/services/agents/__init__.py
  app/services/agents/admin_collector.py  -- activity logging service
  app/services/agents/christy.py          -- ORCID fetch/profile service
  app/services/agents/pirot.py            -- anomaly scoring engine
  app/routers/christy.py                  -- ORCID admin endpoints
  app/routers/pirot.py                    -- anomaly scan/warning endpoints
  app/models.py                           -- +DataAccessLog, QueryHistory, OrcidPublication, OrcidProfile, UserWarning, enums
  app/schemas.py                          -- +PirotScanRequest, UserWarningRead, WarningUpdateRequest, UserProfileReport, QueryHistoryRead, OrcidPublicationRead, OrcidProfileRead, etc.
  app/routers/chat.py                     -- +inline Admin Collector calls
  app/routers/auth.py                     -- +research_interest in register
  app/routers/admin.py                    -- +research_interest in create/update user
  app/main.py                             -- +christy and pirot router includes
  seed.py                                 -- full rewrite: 25 users + simulated queries

agents/
  README.md
  admin_collector/plan.md
  christy/plan.md
  pirot/plan.md
```

### Verified

- Pirot scan correctly flags 4 users: t_chen (high), l_martinez (medium), k_corbett (high), n_pardi (high)
- All 21 legitimate vaccine researchers pass cleanly (interest scores 0.25-1.0)
- Warning CRUD: create via scan, list with filters, patch to reviewed/dismissed
- Profile endpoint returns live scores and query counts
- Christy endpoints: fetch, fetch-all, profile view, cache status all tested

---

## Phase 4: Audit & Usage Tracking

**Status**: Partial (tables exist, not wired)

### What exists
- `AuditLog` model in `models.py` -- table created in SQLite, no middleware writing to it
- `LLMUsage` model in `models.py` -- table created, not wired to Claude API response tracking
- No `GET /admin/usage` endpoint yet
- No `frontend/pages/usage.py` yet

### Remaining work
- Audit logging middleware to auto-log API requests
- Wire LLMUsage tracking into AgentService (capture token counts from Claude responses)
- `GET /admin/usage` endpoint with aggregation queries
- Frontend usage dashboard page

---

## Phase 5: Frontend Enhancements

**Status**: Not started

### Remaining work
- `frontend/pages/warnings.py` -- admin warnings dashboard with Pirot results
- Research interest field in registration form and admin panel
- Per-user detail view with ORCID pubs, query history, divergence scores

---

## Phase 6: Containerization

**Status**: Partial (files exist, not tested)

### What exists
- `Dockerfile` for backend (FastAPI + uvicorn)
- `Dockerfile` for frontend (Streamlit)
- `docker-compose.yml` with both services + SQLite volume
- `.env.example` with all required env vars

### Remaining work
- Test `docker compose up` end-to-end
- Verify volume mounting for SQLite persistence
- Confirm inter-service networking
