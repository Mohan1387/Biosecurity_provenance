# Profiler router -- ORCID profile management (restricted tier only)
import httpx

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_tier
from app.database import get_db
from app.models import OrcidProfile, OrcidPublication, Tier, User
from app.schemas import ProfilerStatusRead, OrcidProfileDetail, OrcidProfileRead, OrcidPublicationRead
from app.services.agents.profiler import build_all_profiles, build_profile_for_user, get_cache_status
from app.services.provenance import verify_row

router = APIRouter(prefix="/admin/profiler", tags=["profiler"])

_restricted = require_tier(Tier.restricted)


@router.post("/fetch/{user_id}", response_model=OrcidProfileRead)
async def fetch_profile(
    user_id: int,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    """Fetch or refresh the ORCID profile for a single user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.orcid_id or user.orcid_id == "0000-0000-0000-0000":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no valid ORCID iD",
        )
    try:
        profile = await build_profile_for_user(db, user, force=force)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Assigned ORCID iD has no public record") from exc
        raise HTTPException(status_code=502, detail=f"ORCID returned HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not reach the ORCID public API") from exc
    return profile


@router.post("/fetch-all", response_model=list[OrcidProfileRead])
async def fetch_all_profiles(
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    """Batch fetch/refresh ORCID profiles for all users with valid ORCID iDs."""
    profiles = await build_all_profiles(db, force=force)
    return profiles


@router.get("/profile/{user_id}", response_model=OrcidProfileDetail)
async def get_profile(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    """View cached ORCID profile and publications for a user."""
    result = await db.execute(
        select(OrcidProfile).where(OrcidProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ORCID profile found. Fetch it first.",
        )

    pubs_result = await db.execute(
        # Publications shown below are operational rows; the receipt preserves
        # the exact source evidence used to build the verified profile.
        select(OrcidPublication)
        .where(OrcidPublication.user_id == user_id)
        .order_by(OrcidPublication.year.desc().nullslast())
    )
    publications = pubs_result.scalars().all()
    for publication in publications:
        await verify_row(db, publication, "profiler")

    await verify_row(db, profile, "profiler")
    return OrcidProfileDetail(
        profile=OrcidProfileRead.model_validate(profile),
        publications=[OrcidPublicationRead.model_validate(p) for p in publications],
    )


@router.get("/status", response_model=ProfilerStatusRead)
async def cache_status(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    """Return cache freshness stats across all ORCID profiles."""
    stats = await get_cache_status(db)
    return stats
