# Detector router -- anomaly detection endpoints (restricted tier only)
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_tier
from app.database import get_db
from app.models import Tier, User, UserWarning, WarningStatus
from app.schemas import (
    DetectorScanRequest,
    QueryHistoryRead,
    UserProfileReport,
    UserWarningRead,
    WarningUpdateRequest,
)
from app.services.agents.detector import get_user_profile_report, scan_all_users, scan_user
from app.services.provenance import verify_row

router = APIRouter(prefix="/admin/detector", tags=["detector"])

_restricted = require_tier(Tier.restricted)


@router.post("/scan", response_model=list[UserWarningRead])
async def trigger_scan(
    body: DetectorScanRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    """Trigger a Detector scan for one or all users."""
    if body.user_id is not None:
        result = await db.execute(select(User).where(User.id == body.user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        warning = await scan_user(db, user)
        return [warning] if warning else []
    else:
        warnings = await scan_all_users(db)
        return warnings


@router.get("/warnings", response_model=list[UserWarningRead])
async def list_warnings(
    status_filter: str | None = None,
    severity: str | None = None,
    user_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    """List warnings with optional filters."""
    query = select(UserWarning).order_by(UserWarning.created_at.desc())

    if status_filter:
        query = query.where(UserWarning.status == WarningStatus(status_filter))
    if severity:
        query = query.where(UserWarning.severity == severity)
    if user_id:
        query = query.where(UserWarning.user_id == user_id)

    result = await db.execute(query)
    return result.scalars().all()


@router.patch("/warnings/{warning_id}", response_model=UserWarningRead)
async def update_warning(
    warning_id: int,
    body: WarningUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_restricted),
):
    """Mark a warning as reviewed or dismissed."""
    result = await db.execute(
        select(UserWarning).where(UserWarning.id == warning_id)
    )
    warning = result.scalar_one_or_none()
    if not warning:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warning not found")

    warning.status = WarningStatus(body.status)
    await verify_row(db, warning, "detector")
    warning.reviewed_by = current_user.id
    warning.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(warning)
    return warning


@router.get("/user/{user_id}/profile", response_model=UserProfileReport)
async def get_profile(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    """View a user's research profile and divergence scores."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    report = await get_user_profile_report(db, user)
    return report


@router.get("/user/{user_id}/queries", response_model=list[QueryHistoryRead])
async def get_user_queries(
    user_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    """View a user's query history for review."""
    from app.models import QueryHistory

    result = await db.execute(
        select(QueryHistory)
        .where(QueryHistory.user_id == user_id)
        .order_by(QueryHistory.timestamp.desc())
        .limit(min(limit, 200))
    )
    return result.scalars().all()
