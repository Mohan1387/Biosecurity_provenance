# Detector Agent -- Research Behavior Anomaly Detection

## Purpose

Detector monitors researcher activity on the PPX platform and flags accounts whose data access and query patterns diverge significantly from their stated research interests and published work. Flagged accounts are escalated for human review.

## Two-Check Verification Model

### Check 1: Stated Research Interest

At registration, each researcher declares their research interest (free-text field stored on their user profile). Detector compares the topics of their actual platform queries and data access against this declared interest.

### Check 2: ORCID Publication History

Detector consumes the researcher's ORCID publication profile built by the **Profiler agent**. Profiler fetches publications from the ORCID public API, extracts metadata, and generates an embedded research profile. Detector compares query activity against this profile as a second validation layer. See `agents/profiler/plan.md`.

### Divergence Scoring

If a researcher's query history is significantly different from **both** their declared interest (Check 1) and their publication history (Check 2), Detector creates a warning on their account flagging it for human review.

## Data Sources

| Source | Description | Access Method |
|--------|-------------|---------------|
| `users` table | Username, ORCID iD, tier, research_interest | SQLite via Logger |
| `audit_log` table | Login history, actions performed | SQLite via Logger |
| `data_access_log` table | Datasets accessed, tier of data, timestamps | SQLite via Logger (new table) |
| `query_history` table | Chat queries sent to the LLM agent | SQLite via Logger (new table) |
| `orcid_profiles` table | Embedded research profile from publications | SQLite via Profiler agent |
| `orcid_publications` table | Raw publication metadata | SQLite via Profiler agent |

## ML Approach

### Topic Characterization

1. **Embedding-based**: Use a sentence transformer (e.g., `all-MiniLM-L6-v2`) to embed:
   - Declared research interest text
   - ORCID publication titles/abstracts
   - Platform query history (chat messages)
   - Dataset names/descriptions accessed

2. **Cosine similarity scoring**:
   - `score_interest` = cosine_sim(query_embeddings, interest_embedding)
   - `score_publications` = cosine_sim(query_embeddings, publication_embeddings)

3. **Divergence threshold**: If both scores fall below a configurable threshold (e.g., 0.3), flag the account.

### Alternative (simpler prototype)

- TF-IDF + topic modeling (LDA) on query history vs interest + publications
- Keyword overlap ratio as a quick heuristic before running full embeddings

## Warning System

```
UserWarning:
  id: int
  user_id: int (FK -> users)
  warning_type: "research_divergence"
  severity: "low" | "medium" | "high"
  detail: JSON {
    interest_score: float,
    publication_score: float,
    flagged_queries: list[str],
    recommended_action: str
  }
  status: "pending" | "reviewed" | "dismissed"
  created_at: datetime
  reviewed_by: int | null (FK -> users, the admin who reviewed)
  reviewed_at: datetime | null
```

## Trigger Modes

1. **Scheduled**: Cron-style batch analysis (e.g., nightly) across all active users
2. **Threshold-based**: After N queries from a user, run a check
3. **On-demand**: Admin triggers a review for a specific user

## Dependencies

- Phase 3 (Audit & Usage Tracking) must be complete -- Detector reads from audit tables
- Logger agent must be populating `data_access_log` and `query_history`
- Profiler agent must be populating `orcid_profiles` and `orcid_publications`
- `research_interest` field must be added to User model / registration
- `sentence-transformers` or `scikit-learn` for ML scoring

## New Files

```
agents/detector/plan.md              -- this file
backend/app/services/agents/detector.py  -- Detector service (scoring, ORCID fetch, warning creation)
backend/app/models.py             -- add UserWarning model, research_interest to User
backend/app/routers/detector.py      -- admin endpoints: trigger scan, view warnings, review
frontend/pages/warnings.py       -- admin UI: warning list, review workflow
```

## API Endpoints (Planned)

- `POST /admin/detector/scan` -- trigger scan for one or all users (restricted)
- `GET /admin/detector/warnings` -- list warnings with filters (restricted)
- `PATCH /admin/detector/warnings/{id}` -- mark reviewed/dismissed (restricted)
- `GET /admin/detector/user/{id}/profile` -- view a user's research profile + scores (restricted)

## Open Questions

- [ ] Should Detector run as a background task or only on-demand?
- [ ] What similarity threshold constitutes "significantly different"? (needs tuning with real data)
- [ ] Should we use Claude to summarize divergence findings in natural language for the reviewer?
- [ ] Rate limiting on ORCID API calls? (public API allows ~24 req/sec)
- [ ] Should warnings auto-restrict a user's tier or only flag for human review?
