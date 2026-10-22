# TCP — Tiered Compute Platform

A prototype platform with tiered user access (Open / Controlled / Restricted), FastAPI backend, Streamlit frontend, and Claude-powered AI agent (Phase 2).

Signed provenance is enforced for Logger, Profiler, Detector and Clusterer.
Configure signing keys before seeding or writing analysis data; see
[provenance setup and verification](PROVENANCE.md). Existing unsigned data is
preserved but rejected as analysis evidence.

For the complete component workflow and diagrams, see the
[provenance working document](PROVENANCE_WORKING_DOCUMENT.md).

## Quick Start (local, no Docker)

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env          # only if .env does not already exist
# Configure DATABASE_URL for a fresh database and the provenance keys (see PROVENANCE.md).
python seed.py                       # fresh DB only: fixed IDs and signed synthetic queries
uvicorn app.main:app --reload        # API at http://localhost:8000

# 2. Frontend (new terminal)
cd frontend
pip install -r requirements.txt
streamlit run app.py                 # UI at http://localhost:8501
```

## Quick Start (Docker)

```bash
cp .env.example .env   # edit .env
docker compose up --build
# API:  http://localhost:8000/docs
# UI:   http://localhost:8501
```

## Default Credentials

| Username | Password | Tier |
|----------|----------|------|
| admin | 1234 | restricted |
| Seeded research users | test1234 | varies |

The seeded accounts and activity are synthetic, with fixed, hardcoded ORCID IDs.
Profiler can fetch public works for those IDs separately; no identity ownership is
verified. Without a fetched profile, Detector records a signed interest-only
decision. **Change these passwords
immediately outside a demo.**

## Access Tiers

| Tier | Data | Tools | Admin |
|------|------|-------|-------|
| Open | Public only | Basic Q&A | No |
| Controlled | + Sensitive datasets | + Analysis tools | No |
| Restricted | All data | All tools | Yes |

## API Docs

Once running: http://localhost:8000/docs (Swagger UI)

## Project Structure

```
2026TCP/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app
│   │   ├── config.py         # env-based settings
│   │   ├── database.py       # async SQLAlchemy
│   │   ├── models.py         # User, AuditLog, LLMUsage
│   │   ├── schemas.py        # Pydantic request/response
│   │   ├── auth.py           # JWT + bcrypt + dependencies
│   │   └── routers/
│   │       ├── auth.py       # register, login, me
│   │       └── admin.py      # user CRUD (restricted only)
│   ├── seed.py               # signed offline demo data for a fresh database
│   ├── check_provenance.py   # verify signed database rows
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── app.py                # Streamlit main
│   ├── pages/
│   │   └── admin.py          # user management panel
│   ├── requirements.txt
│   └── Dockerfile
├── 00_research/
│   └── plan.md
├── docker-compose.yml
├── .env.example
└── README.md
```
