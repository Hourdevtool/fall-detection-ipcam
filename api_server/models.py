from pydantic import BaseModel
from typing import Optional


# ── Auth ──

class GoogleAuthRequest(BaseModel):
    credential: str  # Google ID token from @react-oauth/google


class AuthResponse(BaseModel):
    token: str
    user: dict


# ── Pairing ──

class PairRequest(BaseModel):
    code: str  # 6-digit pairing code


class PairResponse(BaseModel):
    success: bool
    message: str
    system_id: Optional[str] = None


class PairCodeResponse(BaseModel):
    code: str
    expires_in: int  # seconds
    system_id: str


class PairStatusResponse(BaseModel):
    is_paired: bool
    system_id: Optional[str] = None
    paired_at: Optional[float] = None


# ── Cameras ──

class CameraInfo(BaseModel):
    ip: str
    name: str
    has_frame: bool


# ── Fall Events ──

class FallEventResponse(BaseModel):
    id: int
    camera_ip: str
    camera_name: Optional[str]
    snapshot_filename: Optional[str]
    snapshot_url: Optional[str]
    detected_at: float
    detected_at_formatted: str
    duration_seconds: Optional[float]


class FallEventsListResponse(BaseModel):
    events: list[FallEventResponse]
    total: int


# ── Status ──

class SystemStatusResponse(BaseModel):
    status: str  # "online" | "offline"
    cameras_active: int
    system_id: str
    uptime_seconds: float
