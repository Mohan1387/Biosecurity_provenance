# Profiler Agent -- ORCID Research Profile Builder

## Purpose

Profiler is the ORCID integration agent. Given a researcher's ORCID iD, Profiler fetches their publication record from the ORCID public API, extracts topic information, builds an embedded research profile, and caches the result. Other agents (e.g., Detector) consume Profiler's output rather than calling the ORCID API directly.

## Responsibilities

1. **Fetch publications** from the ORCID public API (`pub.orcid.org/v3.0/{orcid}/works`)
2. **Extract metadata**: titles, abstracts, keywords, journal names, publication years
3. **Build topic profile**: Embed extracted text using sentence-transformers to produce a research profile vector
4. **Cache results**: Store raw publication data and computed embeddings in SQLite to avoid redundant API calls
5. **Refresh on demand**: Re-fetch when an admin requests or when cache is stale (configurable TTL, e.g., 30 days)

## Data Flow

```
ORCID Public API
       |
       v
  Profiler Agent
       |
       +---> orcid_publications table (raw metadata cache)
       +---> orcid_profiles table (embedded research profile vectors)
       |
       v
  Detector Agent (consumes profiles for Check 2 scoring)
```

## ORCID API Integration

### Endpoint

```
GET https://pub.orcid.org/v3.0/{orcid}/works
Accept: application/json
```

No authentication required for public data. Rate limit: ~24 requests/second.

### Response Parsing

Extract from each work entry:
- `title.title.value` -- publication title
- `journal-title.value` -- journal/venue name
- `publication-date` -- year of publication
- `external-ids` -- DOIs for potential abstract lookup
- `short-description` -- summary/abstract (when available)

### Abstract Enrichment (Optional)

For works missing `short-description`, optionally fetch abstracts via:
- CrossRef API using DOI: `https://api.crossref.org/works/{doi}`
- Semantic Scholar API: `https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}`

## Data Models

### OrcidPublication

```
OrcidPublication:
  id: int (PK)
  user_id: int (FK -> users)
  orcid_id: str
  title: str
  abstract: str | null
  journal: str | null
  year: int | null
  doi: str | null
  keywords: str | null  -- comma-separated
  fetched_at: datetime
```

### OrcidProfile

```
OrcidProfile:
  id: int (PK)
  user_id: int (FK -> users, unique)
  orcid_id: str
  publication_count: int
  topic_summary: str  -- LLM-generated or TF-IDF keyword summary
  embedding_json: text  -- JSON-serialized profile embedding vector
  last_refreshed: datetime
```

## Trigger Modes

1. **On registration**: When a user registers with an ORCID iD, Profiler queues a profile build
2. **On demand**: Admin triggers a refresh for a specific user via API
3. **Batch refresh**: Scheduled job refreshes profiles older than TTL
4. **Pre-Detector**: Detector calls Profiler to ensure profile is current before scoring

## API Endpoints (Planned)

- `POST /admin/profiler/fetch/{user_id}` -- fetch/refresh ORCID profile for a user (restricted)
- `POST /admin/profiler/fetch-all` -- batch refresh all users with ORCID iDs (restricted)
- `GET /admin/profiler/profile/{user_id}` -- view cached ORCID profile + publications (restricted)
- `GET /admin/profiler/status` -- cache freshness stats (restricted)

## Dependencies

- User model must have `orcid_id` field (already implemented)
- `sentence-transformers` for embedding generation
- `httpx` or `aiohttp` for async ORCID API calls
- Network access to `pub.orcid.org`

## New Files

```
agents/profiler/plan.md                    -- this file
backend/app/services/agents/profiler.py    -- Profiler service (ORCID fetch, profile build, caching)
backend/app/models.py                     -- add OrcidPublication, OrcidProfile models
backend/app/routers/profiler.py            -- admin endpoints for profile management
```

## Open Questions

- [ ] Should Profiler use Claude to generate a natural-language topic summary from publications?
- [ ] Abstract enrichment via CrossRef/Semantic Scholar: worth the extra API calls?
- [ ] Embedding model choice: `all-MiniLM-L6-v2` (fast, 384-dim) vs `all-mpnet-base-v2` (better, 768-dim)?
- [ ] How to handle ORCID iDs with zero publications (new researchers)?
- [ ] Should profile embeddings be stored as binary blobs or JSON arrays?
