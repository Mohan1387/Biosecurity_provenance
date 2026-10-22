# Pydantic schemas for request / response bodies
from datetime import datetime
from pydantic import BaseModel, Field

from app.models import Tier


# ── Auth ──────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=150)
    orcid_id: str = Field(..., pattern=r'^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$', description="ORCID iD (e.g. 0000-0002-1825-0097)")
    password: str = Field(..., min_length=4)
    research_interest: str | None = Field(None, max_length=2000, description="Free-text research interest")


class TokenRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=150)
    password: str = Field(..., min_length=4)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    id: int
    username: str
    orcid_id: str
    tier: Tier
    is_active: bool
    research_interest: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Admin ─────────────────────────────────────────────
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=150)
    orcid_id: str = Field(..., pattern=r'^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$', description="ORCID iD")
    password: str = Field(..., min_length=4)
    tier: Tier = Tier.open
    research_interest: str | None = Field(None, max_length=2000)


class UserUpdate(BaseModel):
    tier: Tier | None = None
    is_active: bool | None = None
    research_interest: str | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(..., min_length=4)


# ── Chat ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)


class ToolCallInfo(BaseModel):
    name: str
    input: dict
    result: str


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[ToolCallInfo] = []
    usage: dict = {}


class ChatMessageRead(BaseModel):
    id: int
    role: str
    content: str
    tool_calls_json: str | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class DeleteUsersRequest(BaseModel):
    user_ids: list[int]


# ── Profiler (ORCID) ──────────────────────────────────
class OrcidPublicationRead(BaseModel):
    id: int
    user_id: int
    orcid_id: str
    title: str
    abstract: str | None = None
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    keywords: str | None = None
    fetched_at: datetime

    model_config = {"from_attributes": True}


class OrcidProfileRead(BaseModel):
    id: int
    user_id: int
    orcid_id: str
    publication_count: int
    topic_summary: str | None = None
    last_refreshed: datetime

    model_config = {"from_attributes": True}


class OrcidProfileDetail(BaseModel):
    profile: OrcidProfileRead
    publications: list[OrcidPublicationRead]


class ProfilerStatusRead(BaseModel):
    total_users_with_orcid: int
    profiles_built: int
    profiles_stale: int
    oldest_refresh: datetime | None = None


# ── Detector (Anomaly Detection) ─────────────────────────
class DetectorScanRequest(BaseModel):
    user_id: int | None = None  # None = scan all users
    force: bool = False


class UserWarningRead(BaseModel):
    id: int
    user_id: int
    warning_type: str
    severity: str
    detail: str | None = None
    status: str
    created_at: datetime
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None

    model_config = {"from_attributes": True}


class WarningUpdateRequest(BaseModel):
    status: str = Field(..., pattern=r'^(reviewed|dismissed)$')


class UserProfileReport(BaseModel):
    user_id: int
    username: str
    orcid_id: str
    research_interest: str | None
    topic_summary: str | None
    profile_source_kind: str | None = None
    interest_score: float | None
    publication_score: float | None
    query_count: int
    warning_count: int


class QueryHistoryRead(BaseModel):
    id: int
    user_id: int
    query_text: str
    tools_invoked: str | None = None
    response_summary: str | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}
