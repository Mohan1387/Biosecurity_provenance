"""Detector Agent -- Research Behavior Anomaly Detection.

Two-check scoring:
  Check 1: Compare query history against declared research interest
  Check 2: Compare query history against ORCID publication profile (via Profiler)

Uses keyword overlap scoring (prototype). Designed to be swapped for
sentence-transformer embeddings when ready.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    OrcidProfile,
    OrcidPublication,
    QueryHistory,
    User,
    UserWarning,
    WarningSeverity,
    WarningStatus,
)

logger = logging.getLogger("detector")
from app.services.provenance import IntegrityError, verify_row, sign_row, reference, persist, source_kind

# Thresholds for divergence detection
INTEREST_THRESHOLD = 0.15   # below this = divergence from stated interest
PUBLICATION_THRESHOLD = 0.15  # below this = divergence from publications
MIN_QUERIES_FOR_SCAN = 5     # need at least this many queries to scan

# Stopwords for keyword extraction
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "of", "for",
    "to", "with", "by", "from", "at", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "can", "could",
    "not", "no", "nor", "so", "if", "then", "than", "that", "this",
    "these", "those", "it", "its", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "over",
    "about", "against", "along", "among", "around", "using", "via",
    "what", "how", "why", "when", "where", "which", "who", "whom",
    "tell", "me", "about", "explain", "describe", "help", "please",
    "could", "you", "your", "know", "think", "like", "want", "need",
}

# Common suffix patterns for simple stemming
_SUFFIX_RULES = [
    ("ization", 4),   # immunization → immuniz
    ("isation", 4),   # organisation → organis
    ("ological", 2),  # immunological → immunolog
    ("ogenic", 2),    # immunogenic → immunog  ... actually let me rethink
]


def _simple_stem(word: str) -> str:
    """Reduce word to a rough stem by stripping common suffixes.

    Intentionally aggressive to maximize recall in keyword matching.
    """
    if len(word) <= 4:
        return word
    # Order matters: longest suffixes first
    for suffix in (
        "ization", "isation", "ological", "ogenicity", "ogenic",
        "ating", "ation", "ional", "ially", "ology",
        "ment", "ness", "ible", "able", "ence", "ance",
        "ious", "eous", "ular", "ular",
        "ity", "ive", "ous", "ing", "ion", "ies", "ism",
        "ent", "ant", "ful", "ize", "ise", "ate", "ure",
        "ial", "ual", "ary",
        "al", "ly", "ed", "er", "es",
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _extract_keywords(text: str) -> Counter[str]:
    """Extract meaningful keywords from text, with simple stemming."""
    words = re.findall(r"[a-z]{3,}", text.lower())
    return Counter(_simple_stem(w) for w in words if w not in _STOPWORDS)


def _keyword_overlap_score(
    keywords_a: Counter[str],
    keywords_b: Counter[str],
) -> float:
    """Compute recall-based overlap: fraction of reference (b) keywords in query (a).

    Answers: "What fraction of the reference profile keywords appear in
    the user's queries?" Returns 0.0 (no overlap) to 1.0 (perfect recall).
    """
    if not keywords_a or not keywords_b:
        return 0.0

    set_a = set(keywords_a.keys())  # query keywords
    set_b = set(keywords_b.keys())  # reference keywords (interest / pubs)

    if not set_b:
        return 0.0

    # Recall: what fraction of reference keywords appear in queries?
    return len(set_a & set_b) / len(set_b)


def _determine_severity(
    interest_score: float,
    publication_score: float,
) -> WarningSeverity:
    """Map divergence scores to severity level."""
    avg = (interest_score + publication_score) / 2
    if avg < 0.05:
        return WarningSeverity.high
    elif avg < 0.10:
        return WarningSeverity.medium
    return WarningSeverity.low


async def scan_user(
    db: AsyncSession,
    user: User,
) -> UserWarning | None:
    """Run Detector two-check scan on a single user.

    Returns a UserWarning if divergence detected, else None.
    """
    # Fetch query history
    result = await db.execute(
        select(QueryHistory)
        .where(QueryHistory.user_id == user.id)
        .order_by(QueryHistory.timestamp.desc())
        .limit(100)
    )
    queries = result.scalars().all()

    evidence = [await verify_row(db, q, "logger") for q in queries]
    query_source_kinds = sorted({source_kind(e) for e in evidence})

    if len(queries) < MIN_QUERIES_FOR_SCAN:
        await persist(db, "detector", "detector_scan", str(user.id),
            {"outcome": "insufficient_queries", "query_count": len(queries)},
            parents=[reference(e) for e in evidence],
            processing={"operation": "research_divergence", "version": 1,
                        "minimum_queries": MIN_QUERIES_FOR_SCAN})
        await db.commit()
        logger.info(
            "User %s has only %d queries, skipping (need %d)",
            user.username, len(queries), MIN_QUERIES_FOR_SCAN,
        )
        return None

    # Build query keyword profile
    query_keywords: Counter[str] = Counter()
    for q in queries:
        query_keywords.update(_extract_keywords(q.query_text))

    # ── Check 1: vs research interest ──
    interest_score = 0.0
    if user.research_interest:
        interest_keywords = _extract_keywords(user.research_interest)
        interest_score = _keyword_overlap_score(query_keywords, interest_keywords)
    else:
        interest_score = 0.5  # no interest declared, neutral

    # ── Check 2: vs ORCID publications (via Profiler) ──
    publication_score = 0.0
    pub_result = await db.execute(
        select(OrcidProfile).where(OrcidProfile.user_id == user.id)
    )
    profile = pub_result.scalar_one_or_none()
    profile_source_kind = None
    profile_evidence_status = "not_fetched"
    if profile is not None:
        evidence.append(await verify_row(db, profile, "profiler"))
        profile_source_kind = source_kind(evidence[-1])
        if profile.orcid_id != user.orcid_id:
            raise IntegrityError("profile_identity_mismatch", str(user.id))
        profile_evidence_status = "available" if profile.publication_count > 0 and profile.topic_summary else "no_public_works"

    if profile_evidence_status == "available":
        pub_keywords = _extract_keywords(profile.topic_summary)
        publication_score = _keyword_overlap_score(query_keywords, pub_keywords)
        has_pub_data = True
    else:
        publication_score = None
        has_pub_data = False

    receipt_args = {"inputs": {"user_id": user.id, "research_interest": user.research_interest,
        "interest_score": interest_score, "publication_score": publication_score,
        "profile_source_kind": profile_source_kind, "profile_evidence_status": profile_evidence_status,
        "query_source_kinds": query_source_kinds},
        "parents": [reference(e) for e in evidence],
        "processing": {"operation": "research_divergence", "version": 1,
            "interest_threshold": INTEREST_THRESHOLD, "publication_threshold": PUBLICATION_THRESHOLD,
            "query_limit": 100, "minimum_queries": MIN_QUERIES_FOR_SCAN}}

    logger.info(
        "Detector scan for %s: interest_score=%.3f, publication_score=%s",
        user.username, interest_score,
        f"{publication_score:.3f}" if publication_score is not None else "N/A",
    )

    # ── Divergence check ──
    # If we have both data sources, both must fail to flag
    # If we only have interest data, interest alone can flag
    if has_pub_data:
        if interest_score >= INTEREST_THRESHOLD or publication_score >= INTEREST_THRESHOLD:
            await persist(db, "detector", "detector_scan", str(user.id), {"outcome": "no_warning"}, **receipt_args)
            await db.commit()
            logger.info("User %s passes Detector checks (two-check)", user.username)
            return None
    else:
        # Only interest check available
        if interest_score >= INTEREST_THRESHOLD:
            await persist(db, "detector", "detector_scan", str(user.id), {"outcome": "no_warning"}, **receipt_args)
            await db.commit()
            logger.info("User %s passes Detector interest check", user.username)
            return None

    # Flag the user
    severity = _determine_severity(
        interest_score,
        publication_score if publication_score is not None else interest_score,
    )

    # Identify the most divergent queries (ones with least keyword overlap)
    flagged_queries = []
    if user.research_interest:
        interest_kw_set = set(_extract_keywords(user.research_interest).keys())
        for q in queries[:20]:
            q_kw = set(_extract_keywords(q.query_text).keys())
            if not q_kw & interest_kw_set:
                flagged_queries.append(q.query_text[:200])
            if len(flagged_queries) >= 5:
                break

    detail = json.dumps({
        "profile_source_kind": profile_source_kind,
        "profile_evidence_status": profile_evidence_status,
        "query_source_kinds": query_source_kinds,
        "interest_score": round(interest_score, 4),
        "publication_score": round(publication_score, 4) if publication_score is not None else None,
        "flagged_queries": flagged_queries,
        "total_queries_analyzed": len(queries),
        "recommended_action": (
            "Review user activity and consider restricting access"
            if severity == WarningSeverity.high
            else "Monitor user activity"
        ),
    })

    warning = UserWarning(
        user_id=user.id,
        warning_type="research_divergence",
        severity=severity,
        detail=detail,
        status=WarningStatus.pending,
        created_at=datetime.now(timezone.utc),
    )
    db.add(warning)
    await sign_row(db, warning, "detector", **receipt_args)
    await db.commit()
    await db.refresh(warning)

    logger.warning(
        "Detector WARNING for %s: severity=%s, interest=%.3f, pubs=%s",
        user.username, severity.value, interest_score,
        f"{publication_score:.3f}" if publication_score is not None else "N/A",
    )
    return warning


async def scan_all_users(
    db: AsyncSession,
) -> list[UserWarning]:
    """Run Detector scan across all active users with sufficient query history."""
    result = await db.execute(
        select(User).where(
            User.is_active == True,  # noqa: E712
            User.username != "admin",
        )
    )
    users = result.scalars().all()

    warnings: list[UserWarning] = []
    for user in users:
        try:
            warning = await scan_user(db, user)
            if warning:
                warnings.append(warning)
        except IntegrityError:
            raise
        except Exception:
            logger.exception("Error scanning user %s", user.username)
    return warnings


async def get_user_profile_report(
    db: AsyncSession,
    user: User,
) -> dict:
    """Build a combined research profile report for admin review."""
    # Query count
    q_count = await db.execute(
        select(func.count()).select_from(QueryHistory).where(
            QueryHistory.user_id == user.id
        )
    )
    query_count = q_count.scalar() or 0

    # Warning count
    w_count = await db.execute(
        select(func.count()).select_from(UserWarning).where(
            UserWarning.user_id == user.id,
            UserWarning.status == WarningStatus.pending,
        )
    )
    warning_count = w_count.scalar() or 0

    # ORCID profile
    profile_result = await db.execute(
        select(OrcidProfile).where(OrcidProfile.user_id == user.id)
    )
    profile = profile_result.scalar_one_or_none()
    profile_source_kind = None
    if profile:
        profile_receipt = await verify_row(db, profile, "profiler")
        profile_source_kind = source_kind(profile_receipt)

    # Compute live scores
    interest_score = None
    publication_score = None

    result = await db.execute(
        select(QueryHistory)
        .where(QueryHistory.user_id == user.id)
        .order_by(QueryHistory.timestamp.desc())
        .limit(100)
    )
    queries = result.scalars().all()

    if queries:
        for q in queries:
            await verify_row(db, q, "logger")
        query_keywords: Counter[str] = Counter()
        for q in queries:
            query_keywords.update(_extract_keywords(q.query_text))

        if user.research_interest:
            interest_keywords = _extract_keywords(user.research_interest)
            interest_score = round(
                _keyword_overlap_score(query_keywords, interest_keywords), 4
            )

        if profile and profile.topic_summary:
            pub_keywords = _extract_keywords(profile.topic_summary)
            publication_score = round(
                _keyword_overlap_score(query_keywords, pub_keywords), 4
            )

    return {
        "user_id": user.id,
        "username": user.username,
        "orcid_id": user.orcid_id,
        "research_interest": user.research_interest,
        "topic_summary": profile.topic_summary if profile else None,
        "profile_source_kind": profile_source_kind,
        "interest_score": interest_score,
        "publication_score": publication_score,
        "query_count": query_count,
        "warning_count": warning_count,
    }
