# Admin router — user CRUD (restricted tier only)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password, require_tier
from app.database import get_db
from app.models import Tier, User
from app.schemas import DeleteUsersRequest, PasswordReset, UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])

_restricted = require_tier(Tier.restricted)


@router.get("/users", response_model=list[UserRead])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    result = await db.execute(select(User).order_by(User.id))
    return result.scalars().all()


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )
    existing_orcid = await db.execute(select(User).where(User.orcid_id == body.orcid_id))
    if existing_orcid.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ORCID iD already registered",
        )
    user = User(
        username=body.username,
        orcid_id=body.orcid_id,
        hashed_password=hash_password(body.password),
        tier=body.tier,
        research_interest=body.research_interest,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.tier is not None:
        user.tier = body.tier
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.research_interest is not None:
        user.research_interest = body.research_interest

    await db.commit()
    await db.refresh(user)
    return user


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: int,
    body: PasswordReset,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hashed_password = hash_password(body.new_password)
    await db.commit()


@router.post("/users/delete", status_code=status.HTTP_200_OK)
async def delete_users(
    body: DeleteUsersRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(_restricted),
):
    # Protect the seeded admin account (username='admin') from deletion
    result = await db.execute(
        select(User).where(User.id.in_(body.user_ids))
    )
    users_to_delete = result.scalars().all()

    deleted = []
    skipped = []
    for u in users_to_delete:
        if u.username == "admin":
            skipped.append(u.username)
        else:
            await db.delete(u)
            deleted.append(u.username)

    await db.commit()
    return {"deleted": deleted, "skipped": skipped}
