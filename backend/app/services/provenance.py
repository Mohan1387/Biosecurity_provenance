"""TCP receipt protocol v1: deterministic UTF-8 JSON, SHA-256, Ed25519.

Keys and trust registry are deployment configuration, never database content.
Single-process deployment is one security boundary, regardless of key count.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import select

from app.models import ProvenanceReceipt

COMPONENTS = {"logger", "profiler", "detector", "clusterer"}


class IntegrityError(Exception):
    def __init__(self, reason: str, subject: str = ""):
        self.reason, self.subject = reason, subject
        super().__init__(f"{reason}: {subject}")


def normalize(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    return value


def canonical(value) -> bytes:
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def snapshot(row) -> dict:
    # Review state is mutable workflow metadata, not the Detector's signed result.
    excluded = {"status", "reviewed_by", "reviewed_at"} if row.__tablename__ == "user_warnings" else set()
    return normalize({c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in excluded})


def registry() -> dict:
    path = os.getenv("PROVENANCE_REGISTRY")
    if not path:
        raise IntegrityError("signing_not_configured")
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise IntegrityError("invalid_trust_registry") from exc


def sign(component: str, subject_type: str, subject_id: str, output, *, inputs=None, parents=None, processing=None) -> dict:
    if component not in COMPONENTS:
        raise IntegrityError("unknown_component", component)
    trust = registry()
    try:
        kid = trust["active"][component]
        entry = trust["keys"][kid]
        if entry["status"] != "active":
            raise IntegrityError("inactive_signing_key", component)
        path = os.environ[f"PROVENANCE_{component.upper()}_KEY"]
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Ed25519 required")
    except (KeyError, OSError, ValueError, TypeError) as exc:
        raise IntegrityError("signing_key_unavailable", component) from exc
    payload = normalize({
        "schema": "tcp-receipt-v1", "receipt_id": str(uuid4()), "component": component,
        "key_id": kid, "subject_type": subject_type, "subject_id": str(subject_id),
        "issued_at": datetime.now(timezone.utc), "output": output,
        "output_hash": digest(output), "inputs": inputs or {}, "input_hash": digest(inputs or {}),
        "parents": parents or [], "processing": processing or {},
    })
    envelope = {"payload": payload, "signature": base64.b64encode(key.sign(canonical(payload))).decode()}
    verify_signature(envelope, component)  # detect key/registry misconfiguration before persisting
    return envelope


def verify_signature(envelope: dict, expected_component: str | None = None) -> dict:
    try:
        p = envelope["payload"]
        entry = registry()["keys"][p["key_id"]]
        if p["schema"] != "tcp-receipt-v1" or p["component"] not in COMPONENTS:
            raise IntegrityError("unsupported_receipt")
        if entry["component"] != p["component"] or (expected_component and p["component"] != expected_component):
            raise IntegrityError("wrong_signer")
        if entry["status"] not in ("active", "retired"):
            raise IntegrityError("revoked_key")
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(entry["public_key"], validate=True))
        public.verify(base64.b64decode(envelope["signature"], validate=True), canonical(p))
        if p["output_hash"] != digest(p["output"]) or p["input_hash"] != digest(p["inputs"]):
            raise IntegrityError("content_hash_mismatch")
        return p
    except IntegrityError:
        raise
    except (KeyError, TypeError, ValueError, InvalidSignature) as exc:
        raise IntegrityError("invalid_signature_or_receipt") from exc


async def persist(db, component, subject_type, subject_id, output, **kwargs) -> dict:
    envelope = sign(component, subject_type, str(subject_id), output, **kwargs)
    p = envelope["payload"]
    db.add(ProvenanceReceipt(receipt_id=p["receipt_id"], component=component,
        subject_type=subject_type, subject_id=str(subject_id), envelope_json=canonical(envelope).decode()))
    await db.flush()
    return envelope


async def verify_chain(db, receipt_id: str, *, seen=None, cache=None) -> dict:
    seen = set() if seen is None else seen
    cache = {} if cache is None else cache
    if receipt_id in seen or len(seen) >= 32:
        raise IntegrityError("cyclic_or_excessive_chain", receipt_id)
    if receipt_id in cache:
        return cache[receipt_id]
    row = (await db.execute(select(ProvenanceReceipt).where(ProvenanceReceipt.receipt_id == receipt_id))).scalar_one_or_none()
    if row is None:
        raise IntegrityError("missing_receipt", receipt_id)
    try:
        envelope = json.loads(row.envelope_json)
    except ValueError as exc:
        raise IntegrityError("malformed_receipt", receipt_id) from exc
    p = verify_signature(envelope)
    if (p["receipt_id"], p["component"], p["subject_type"], p["subject_id"]) != (row.receipt_id, row.component, row.subject_type, row.subject_id):
        raise IntegrityError("receipt_binding_mismatch", receipt_id)
    for parent in p["parents"]:
        result = await verify_chain(db, parent["receipt_id"], seen=seen | {receipt_id}, cache=cache)
        if digest(result) != parent["receipt_hash"]:
            raise IntegrityError("parent_hash_mismatch", receipt_id)
    cache[receipt_id] = envelope
    return envelope


def reference(envelope):
    return {"receipt_id": envelope["payload"]["receipt_id"], "receipt_hash": digest(envelope)}


def source_kind(envelope: dict) -> str:
    """Read signed source metadata, including older synthetic seed receipts."""
    processing = envelope["payload"]["processing"]
    return processing.get("source_kind") or (
        "synthetic" if processing.get("operation") in {"synthetic_seed", "synthetic_seed_profile", "synthetic_seed_publication"}
        else "unknown"
    )


async def verify_row(db, row, component: str) -> dict:
    record = (await db.execute(select(ProvenanceReceipt).where(
        ProvenanceReceipt.subject_type == row.__tablename__, ProvenanceReceipt.subject_id == str(row.id)
    ).order_by(ProvenanceReceipt.id.desc()).limit(1))).scalar_one_or_none()
    if record is None:
        raise IntegrityError("unsigned_input", f"{row.__tablename__}/{row.id}")
    envelope = await verify_chain(db, record.receipt_id)
    p = verify_signature(envelope, component)
    if p["output_hash"] != digest(snapshot(row)):
        raise IntegrityError("live_record_mismatch", f"{row.__tablename__}/{row.id}")
    return envelope


async def sign_row(db, row, component, **kwargs):
    await db.flush()
    return await persist(db, component, row.__tablename__, row.id, snapshot(row), **kwargs)
