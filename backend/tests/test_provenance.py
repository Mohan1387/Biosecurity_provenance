import copy
import json
import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base
from app.models import User, Tier, QueryHistory, OrcidProfile, ProvenanceReceipt, UserWarning
from app.services.provenance import (sign, verify_signature, IntegrityError, verify_row,
    sign_row, reference, verify_chain, canonical)
from app.services.agents.logger import record_query
from app.services.agents.detector import scan_user
from app.services.agents.profiler import build_profile_for_user
from app.routers.clusterer import analyze
from app.routers.provenance import verify_run
from provenance_keys import provision


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    directory = tmp_path / "keys"
    provision(directory)
    monkeypatch.setenv("PROVENANCE_REGISTRY", str(directory / "registry.json"))
    for component in ("logger", "profiler", "detector", "clusterer"):
        monkeypatch.setenv(f"PROVENANCE_{component.upper()}_KEY", str(directory / f"{component}.pem"))
    return directory


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.mark.parametrize("component", ["logger", "profiler", "detector", "clusterer"])
def test_signing_and_tamper(component):
    envelope = sign(component, "example", "1", {"text": "résumé", "score": 0.25})
    assert verify_signature(envelope, component)["component"] == component
    changed = copy.deepcopy(envelope)
    changed["payload"]["output"]["score"] = 0.5
    with pytest.raises(IntegrityError):
        verify_signature(changed)
    with pytest.raises(IntegrityError, match="wrong_signer"):
        verify_signature(envelope, "different")


def test_retirement_revocation_and_missing_key(keys, monkeypatch):
    envelope = sign("logger", "query", "1", {})
    path = keys / "registry.json"
    trust = json.loads(path.read_text())
    kid = trust["active"]["logger"]
    trust["keys"][kid]["status"] = "retired"
    path.write_text(json.dumps(trust))
    verify_signature(envelope)
    with pytest.raises(IntegrityError, match="inactive_signing_key"):
        sign("logger", "query", "2", {})
    trust["keys"][kid]["status"] = "revoked"
    path.write_text(json.dumps(trust))
    with pytest.raises(IntegrityError, match="revoked_key"):
        verify_signature(envelope)
    monkeypatch.delenv("PROVENANCE_REGISTRY")
    with pytest.raises(IntegrityError, match="signing_not_configured"):
        sign("logger", "query", "2", {})


def test_canonical_order_and_dates():
    assert canonical({"b": 2, "a": 1}) == canonical({"a": 1, "b": 2})
    assert canonical(datetime(2026, 1, 1)) == canonical(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        canonical({"score": float("nan")})


@pytest.mark.asyncio
async def test_logger_live_tampering_and_rollback(db):
    q = await record_query(db, 1, "biology")
    await db.commit()
    await db.refresh(q)
    await verify_row(db, q, "logger")
    q.query_text = "modified"
    with pytest.raises(IntegrityError, match="live_record_mismatch"):
        await verify_row(db, q, "logger")
    await db.rollback()
    await record_query(db, 1, "uncommitted")
    await db.rollback()
    assert (await db.scalar(select(func.count()).select_from(QueryHistory))) == 1
    assert (await db.scalar(select(func.count()).select_from(ProvenanceReceipt))) == 1


async def make_user(db):
    user = User(username="researcher", orcid_id="0000-0001-0000-0001", hashed_password="unused", tier=Tier.open, research_interest="immunology vaccine")
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_profiler_detector_historical_chain(db, monkeypatch):
    user = await make_user(db)
    async def fetch(_):
        return [{"title": "Immunology vaccine research", "year": 2026, "doi": "example"}]
    monkeypatch.setattr("app.services.agents.profiler.fetch_orcid_works", fetch)
    profile = await build_profile_for_user(db, user)
    for i in range(5):
        await record_query(db, user.id, f"astronomy galaxies planets {i}")
    await db.commit()
    warning = await scan_user(db, user)
    assert warning is not None
    envelope = await verify_row(db, warning, "detector")
    assert len(envelope["payload"]["parents"]) == 6
    warning.status = "reviewed"
    await verify_row(db, warning, "detector")
    await build_profile_for_user(db, user, force=True)
    await verify_chain(db, envelope["payload"]["receipt_id"])
    parent_id = envelope["payload"]["parents"][0]["receipt_id"]
    parent = (await db.execute(select(ProvenanceReceipt).where(ProvenanceReceipt.receipt_id == parent_id))).scalar_one()
    parent.envelope_json = parent.envelope_json.replace("astronomy", "tampered")
    await db.flush()
    with pytest.raises(IntegrityError):
        await verify_row(db, warning, "detector")


@pytest.mark.asyncio
async def test_unsigned_rejected_but_missing_profile_uses_interest_only(db):
    user = await make_user(db)
    q = QueryHistory(user_id=user.id, query_text="unsigned")
    db.add(q)
    await db.flush()
    with pytest.raises(IntegrityError, match="unsigned_input"):
        await scan_user(db, user)
    await db.delete(q)
    for i in range(5):
        await record_query(db, user.id, f"science {i}")
    warning = await scan_user(db, user)
    assert warning is not None
    assert json.loads(warning.detail)["profile_evidence_status"] == "not_fetched"
    envelope = await verify_row(db, warning, "detector")
    assert len(envelope["payload"]["parents"]) == 5


@pytest.mark.asyncio
async def test_clusterer_artifacts(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.routers.clusterer.OUTPUT_ROOT", tmp_path / "reports")
    user = await make_user(db)
    for text in ["vaccine immunology", "vaccine research", "biology medicine"]:
        await record_query(db, user.id, text)
    await db.commit()
    result = await analyze(db, save=True)
    verified = await verify_run(result["run_id"], db)
    assert verified["verified"] is True
    artifact = tmp_path / "reports" / result["run_id"] / "summary_report.json"
    artifact.write_text("{}")
    with pytest.raises(IntegrityError, match="artifact_mismatch"):
        await verify_run(result["run_id"], db)


@pytest.mark.asyncio
async def test_missing_parent_and_subject_binding(db):
    q = await record_query(db, 1, "science")
    envelope = await verify_row(db, q, "logger")
    row = (await db.execute(select(ProvenanceReceipt))).scalar_one()
    row.subject_id = "999"
    await db.flush()
    with pytest.raises(IntegrityError, match="receipt_binding_mismatch"):
        await verify_chain(db, envelope["payload"]["receipt_id"])
    row.subject_id = str(q.id)
    await db.delete(row)
    await db.flush()
    with pytest.raises(IntegrityError, match="missing_receipt"):
        await verify_chain(db, envelope["payload"]["receipt_id"])


@pytest.mark.asyncio
async def test_api_authorization_integrity_audit(db, monkeypatch):
    import httpx
    from app.main import app
    from app.auth import get_current_user
    from app.database import get_db
    from app.models import AuditLog
    user = await make_user(db)
    q = QueryHistory(user_id=user.id, query_text="legacy")
    db.add(q)
    await db.commit()
    monkeypatch.setattr("app.main.async_session", async_sessionmaker(db.bind, expire_on_commit=False))
    async def database():
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: user
    url = f"/api/v1/admin/provenance/records/query_history/{q.id}/verify"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(url)).status_code == 403
            user.tier = Tier.restricted
            await db.commit()
            response = await client.get(url)
            assert response.status_code == 409
            assert response.json()["reason"] == "unsigned_input"
        assert (await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "integrity_failure"))) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_failed_signing_persists_nothing(db, monkeypatch):
    monkeypatch.delenv("PROVENANCE_LOGGER_KEY")
    with pytest.raises(IntegrityError):
        await record_query(db, 1, "cannot sign")
    await db.rollback()
    assert (await db.scalar(select(func.count()).select_from(QueryHistory))) == 0
    assert (await db.scalar(select(func.count()).select_from(ProvenanceReceipt))) == 0


@pytest.mark.asyncio
async def test_no_warning_and_skipped_decisions_signed(db):
    user = await make_user(db)
    assert await scan_user(db, user) is None
    row = (await db.execute(select(ProvenanceReceipt))).scalar_one()
    assert (await verify_chain(db, row.receipt_id))["payload"]["output"]["outcome"] == "insufficient_queries"
    profile = OrcidProfile(user_id=user.id, orcid_id=user.orcid_id, topic_summary="immunology vaccine", publication_count=0)
    db.add(profile)
    await sign_row(db, profile, "profiler")
    for i in range(5):
        await record_query(db, user.id, "immunology vaccine research")
    assert await scan_user(db, user) is None
    last = (await db.execute(select(ProvenanceReceipt).order_by(ProvenanceReceipt.id.desc()).limit(1))).scalar_one()
    assert (await verify_chain(db, last.receipt_id))["payload"]["output"]["outcome"] == "no_warning"


@pytest.mark.asyncio
async def test_data_access_signing(db):
    from app.services.agents.logger import record_data_access
    row = await record_data_access(db, 1, "employee_metrics", Tier.controlled)
    await db.commit()
    await verify_row(db, row, "logger")
    row.dataset_name = "changed"
    with pytest.raises(IntegrityError, match="live_record_mismatch"):
        await verify_row(db, row, "logger")
