"""Profiler Agent -- ORCID Research Profile Builder.

Fetches publications from the ORCID public API, extracts metadata,
builds a topic summary, and caches results in SQLite.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrcidProfile, OrcidPublication, User, ProvenanceReceipt
from app.services.provenance import sign_row, verify_row, reference

logger = logging.getLogger("profiler")

ORCID_API_BASE = "https://pub.orcid.org/v3.0"
DEFAULT_TTL_DAYS = 30


async def fetch_orcid_works(orcid_id: str) -> list[dict]:
    """Fetch works from the ORCID public API and return parsed entries."""
    url = f"{ORCID_API_BASE}/{orcid_id}/works"
    headers = {"Accept": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    works: list[dict] = []
    for group in data.get("group", []):
        summaries = group.get("work-summary", [])
        if not summaries:
            continue
        summary = summaries[0]  # take the first (preferred) summary

        title_obj = summary.get("title")
        title = (
            title_obj.get("title", {}).get("value", "")
            if title_obj
            else ""
        )
        if not title:
            continue

        journal = None
        jt = summary.get("journal-title")
        if jt:
            journal = jt.get("value")

        year = None
        pub_date = summary.get("publication-date")
        if pub_date and pub_date.get("year"):
            try:
                year = int(pub_date["year"]["value"])
            except (ValueError, TypeError):
                pass

        doi = None
        ext_ids = summary.get("external-ids", {}).get("external-id", [])
        for eid in ext_ids:
            if eid.get("external-id-type") == "doi":
                doi = eid.get("external-id-value")
                break

        works.append({
            "title": title,
            "journal": journal,
            "year": year,
            "doi": doi,
        })

    return works


def build_topic_summary(publications: list[dict]) -> str:
    """Build a simple keyword-based topic summary from publication titles.

    Uses TF-IDF-style keyword extraction: collect meaningful words from
    titles and rank by frequency.  This avoids a heavy ML dependency for
    the prototype and can be swapped for sentence-transformers later.
    """
    import re
    from collections import Counter

    stopwords = {
        "a", "an", "the", "and", "or", "but", "in", "on", "of", "for",
        "to", "with", "by", "from", "at", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "shall", "should", "may", "might", "can", "could",
        "not", "no", "nor", "so", "if", "then", "than", "that", "this",
        "these", "those", "it", "its", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "under", "over",
        "about", "against", "along", "among", "around", "using", "via",
        "based", "study", "analysis", "approach", "new", "novel", "role",
        "effect", "effects", "case", "review", "research", "results",
    }

    word_counts: Counter[str] = Counter()
    for pub in publications:
        words = re.findall(r"[a-z]{3,}", pub.get("title", "").lower())
        word_counts.update(w for w in words if w not in stopwords)

    top = word_counts.most_common(20)
    if not top:
        return "No topics extracted"
    return ", ".join(word for word, _ in top)


async def build_profile_for_user(
    db: AsyncSession,
    user: User,
    *,
    force: bool = False,
) -> OrcidProfile:
    """Fetch ORCID data, store publications, and build/update the profile.

    If a cached profile exists and is within TTL (and force=False), returns
    the cached version.
    """
    # Check for existing fresh profile
    if not force:
        result = await db.execute(
            select(OrcidProfile).where(OrcidProfile.user_id == user.id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            cutoff = datetime.now(timezone.utc) - timedelta(days=DEFAULT_TTL_DAYS)
            refreshed = existing.last_refreshed
            if refreshed:
                # SQLite may return naive datetimes; make comparable
                if refreshed.tzinfo is None:
                    refreshed = refreshed.replace(tzinfo=timezone.utc)
                if refreshed >= cutoff:
                    await verify_row(db, existing, "profiler")
                    logger.info("Profile for user %s is fresh, skipping fetch", user.username)
                    return existing

    # Fetch from ORCID API
    logger.info("Fetching ORCID works for %s (%s)", user.username, user.orcid_id)
    raw_works = await fetch_orcid_works(user.orcid_id)

    # Clear old publications for this user
    await db.execute(
        delete(OrcidPublication).where(OrcidPublication.user_id == user.id)
    )

    # Store new publications
    now = datetime.now(timezone.utc)
    publication_receipts = []
    for work in raw_works:
        pub = OrcidPublication(
            user_id=user.id,
            orcid_id=user.orcid_id,
            title=work["title"],
            journal=work.get("journal"),
            year=work.get("year"),
            doi=work.get("doi"),
            fetched_at=now,
        )
        db.add(pub)
        publication_receipts.append(await sign_row(db, pub, "profiler", inputs={"source": work,
            "url": f"{ORCID_API_BASE}/{user.orcid_id}/works"},
            processing={"operation": "parse_orcid_publication", "version": 1,
                        "source_kind": "orcid_public_api"}))

    # Build topic summary
    topic_summary = build_topic_summary(raw_works) if raw_works else ""

    # Upsert profile
    result = await db.execute(
        select(OrcidProfile).where(OrcidProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        profile.publication_count = len(raw_works)
        profile.topic_summary = topic_summary
        profile.embedding_json = None  # placeholder for future embeddings
        profile.last_refreshed = now
    else:
        profile = OrcidProfile(
            user_id=user.id,
            orcid_id=user.orcid_id,
            publication_count=len(raw_works),
            topic_summary=topic_summary,
            embedding_json=None,
            last_refreshed=now,
        )
        db.add(profile)

    await db.flush()
    previous = await db.execute(select(ProvenanceReceipt).where(
        ProvenanceReceipt.subject_type == "orcid_profiles",
        ProvenanceReceipt.subject_id == str(profile.id),
    ))
    version = len(previous.scalars().all()) + 1
    await sign_row(db, profile, "profiler", inputs={
        "orcid_id": user.orcid_id, "source_url": f"{ORCID_API_BASE}/{user.orcid_id}/works",
        "publications": raw_works, "retrieved_at": now,
    }, parents=[reference(e) for e in publication_receipts],
    processing={"operation": "build_topic_summary", "version": 1, "profile_version": version,
                   "source_kind": "orcid_public_api",
                   "source_trust": "ORCID HTTPS response observed by Profiler; not signed by ORCID"})
    await db.commit()
    await db.refresh(profile)
    logger.info(
        "Profile built for %s: %d publications, topics: %s",
        user.username, len(raw_works), topic_summary[:80],
    )
    return profile


async def build_all_profiles(
    db: AsyncSession,
    *,
    force: bool = False,
) -> list[OrcidProfile]:
    """Build/refresh profiles for all users that have an ORCID iD."""
    result = await db.execute(
        select(User).where(
            User.orcid_id.isnot(None),
            User.orcid_id != "",
            User.orcid_id != "0000-0000-0000-0000",  # skip placeholder admin
        )
    )
    users = result.scalars().all()

    profiles: list[OrcidProfile] = []
    for user in users:
        try:
            profile = await build_profile_for_user(db, user, force=force)
            profiles.append(profile)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "ORCID API error for %s (%s): %s",
                user.username, user.orcid_id, exc,
            )
        except httpx.RequestError as exc:
            logger.warning(
                "Network error fetching ORCID for %s: %s",
                user.username, exc,
            )
    return profiles


async def get_cache_status(db: AsyncSession) -> dict:
    """Return aggregate cache freshness stats."""
    # Total users with an ORCID
    total_q = await db.execute(
        select(func.count()).select_from(User).where(
            User.orcid_id.isnot(None),
            User.orcid_id != "",
            User.orcid_id != "0000-0000-0000-0000",
        )
    )
    total_users = total_q.scalar() or 0

    # Profiles built
    built_q = await db.execute(
        select(func.count()).select_from(OrcidProfile)
    )
    profiles_built = built_q.scalar() or 0

    # Stale profiles
    cutoff = datetime.now(timezone.utc) - timedelta(days=DEFAULT_TTL_DAYS)
    stale_q = await db.execute(
        select(func.count()).select_from(OrcidProfile).where(
            OrcidProfile.last_refreshed < cutoff
        )
    )
    profiles_stale = stale_q.scalar() or 0

    # Oldest refresh
    oldest_q = await db.execute(
        select(func.min(OrcidProfile.last_refreshed))
    )
    oldest = oldest_q.scalar()

    return {
        "total_users_with_orcid": total_users,
        "profiles_built": profiles_built,
        "profiles_stale": profiles_stale,
        "oldest_refresh": oldest,
    }
