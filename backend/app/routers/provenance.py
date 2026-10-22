"""Restricted evidence inspection; verification always recomputes signatures."""
import json
import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.auth import require_tier
from app.database import get_db
from app.models import Tier, ProvenanceReceipt, QueryHistory, DataAccessLog, OrcidProfile, UserWarning
from app.services.provenance import verify_chain, verify_row, IntegrityError

router = APIRouter(prefix="/admin/provenance", tags=["provenance"], dependencies=[Depends(require_tier(Tier.restricted))])


@router.get("/receipts")
async def receipts(subject_type: str, subject_id: str, db=Depends(get_db)):
    rows = (await db.execute(select(ProvenanceReceipt).where(
        ProvenanceReceipt.subject_type == subject_type, ProvenanceReceipt.subject_id == subject_id
    ).order_by(ProvenanceReceipt.id.desc()))).scalars().all()
    return [{"receipt_id": r.receipt_id, "component": r.component} for r in rows]


@router.get("/receipts/{receipt_id}/verify")
async def verify(receipt_id: str, db=Depends(get_db)):
    cache = {}
    envelope = await verify_chain(db, receipt_id, cache=cache)
    return {"verified": True, "receipt": envelope, "evidence": list(cache.values()),
            "scope": "historical signed snapshots; does not attest truth or completeness"}


@router.get("/records/{subject_type}/{subject_id}/verify")
async def verify_record(subject_type: str, subject_id: int, db=Depends(get_db)):
    mapping = {"query_history": (QueryHistory, "logger"), "data_access_log": (DataAccessLog, "logger"),
               "orcid_profiles": (OrcidProfile, "profiler"), "user_warnings": (UserWarning, "detector")}
    if subject_type not in mapping:
        raise IntegrityError("unsupported_subject", subject_type)
    model, component = mapping[subject_type]
    row = await db.get(model, subject_id)
    if row is None:
        raise IntegrityError("missing_record", str(subject_id))
    envelope = await verify_row(db, row, component)
    return {"verified": True, "receipt_id": envelope["payload"]["receipt_id"]}


@router.get("/runs/{run_id}/verify")
async def verify_run(run_id: str, db=Depends(get_db)):
    from app.routers.clusterer import OUTPUT_ROOT
    try:
        UUID(run_id)
    except ValueError as exc:
        raise IntegrityError("invalid_run_id") from exc
    row = (await db.execute(select(ProvenanceReceipt).where(
        ProvenanceReceipt.subject_type == "clusterer_run", ProvenanceReceipt.subject_id == run_id
    ))).scalar_one_or_none()
    if row is None:
        raise IntegrityError("missing_run", run_id)
    envelope = await verify_chain(db, row.receipt_id)
    p = envelope["payload"]
    if p["component"] != "clusterer":
        raise IntegrityError("wrong_signer", run_id)
    if p["output"]["artifacts"]:
        from app.services.provenance import canonical
        receipt_file = OUTPUT_ROOT / run_id / "receipt.json"
        if not receipt_file.is_file() or receipt_file.read_bytes() != canonical(envelope):
            raise IntegrityError("artifact_mismatch", "receipt.json")
    for name, expected in p["output"]["artifacts"].items():
        if name not in {"persona_report.json", "anomaly_report.json", "summary_report.json", "user_feature_matrix.csv", "event_anomalies.csv", "user_anomalies.csv"}:
            raise IntegrityError("invalid_artifact_name")
        path = OUTPUT_ROOT / run_id / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise IntegrityError("artifact_mismatch", name)
    return {"verified": True, "receipt_id": row.receipt_id, "result": p["output"]["result"]}
