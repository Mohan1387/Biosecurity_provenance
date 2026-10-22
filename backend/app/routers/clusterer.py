# Clusterer router -- usage persona & anomaly detection endpoints (restricted tier only)
from pathlib import Path
import asyncio
import hashlib
from uuid import uuid4
import pandas as pd
from sqlalchemy import select
from app.database import get_db
from app.models import QueryHistory
from app.services.provenance import verify_row, reference, persist, canonical, source_kind
from app.services.agents.clusterer.adapter import build_flat_table

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_tier
from app.models import Tier, User

router = APIRouter(prefix="/admin/clusterer", tags=["clusterer"])

_restricted = require_tier(Tier.restricted)

OUTPUT_ROOT = Path(__file__).resolve().parent.parent.parent / "output" / "clusterer"


async def analyze(db, save=False):
    queries = (await db.execute(select(QueryHistory).order_by(QueryHistory.user_id, QueryHistory.timestamp))).scalars().all()
    evidence = [await verify_row(db, q, "logger") for q in queries]
    source_kinds = sorted({source_kind(e) for e in evidence})
    users = (await db.execute(select(User))).scalars().all()
    user_data = [{"user_id": u.id, "username": u.username, "tier": u.tier.value, "created_at": u.created_at} for u in users]
    query_data = [{"prompt_id": q.id, "user_id": q.user_id, "prompt_text": q.query_text,
                   "response_text": q.response_summary, "event_timestamp": q.timestamp} for q in queries]
    if not query_data:
        raise HTTPException(422, "No query history records found")
    flat = build_flat_table(pd.DataFrame(user_data), pd.DataFrame(query_data))
    run_id = str(uuid4())
    output_dir = OUTPUT_ROOT / run_id if save else None
    from app.services.agents.clusterer.pipeline import run_pipeline
    try:
        result = await asyncio.to_thread(run_pipeline, "", str(output_dir) if save else None, flat_table=flat)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    files = {}
    result["summary"]["input_source_kinds"] = source_kinds
    if output_dir:
        files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output_dir.iterdir()) if p.is_file()}
    envelope = await persist(db, "clusterer", "clusterer_run", run_id, {"result": result, "artifacts": files},
        parents=[reference(e) for e in evidence], inputs={"users": user_data},
        processing={"version": 1, "min_personas": 2, "max_personas": 6, "max_text_features": 100,
                    "svd_components": 20, "random_state": 42, "lof_contamination": 0.1, "event_z_threshold": 3.0})
    if output_dir:
        (output_dir / "receipt.json").write_bytes(canonical(envelope))
    await db.commit()
    return {**result, "run_id": run_id, "provenance": envelope}


@router.post("/analyze")
async def run_analysis(
    _current_user: User = Depends(_restricted),
    db=Depends(get_db),
):
    """Run the full clusterer persona + anomaly pipeline against the current DB."""
    return await analyze(db)


@router.post("/analyze/save")
async def run_analysis_with_save(
    _current_user: User = Depends(_restricted),
    db=Depends(get_db),
):
    """Run the pipeline and persist CSV/JSON artifacts to output/clusterer/."""
    return await analyze(db, save=True)
