"""
Fall Guard API Server
=====================
FastAPI backend that bridges the detection system with the mobile web app.
Run with: python -m api_server.server
"""

import os
import sys
import time
from datetime import datetime
from contextlib import asynccontextmanager



from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
import asyncio
import ipaddress

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from api_server.database import init_db, upsert_user, get_user_by_id, get_fall_events, get_fall_event_by_id, get_active_pairing, activate_pairing as db_activate_pairing, deactivate_pairing
from api_server.auth import verify_google_token, create_jwt_token, get_current_user
from api_server.pairing import get_or_create_system_id, create_new_pair_code, validate_pair_code, get_current_pair_code
from api_server.models import (
    GoogleAuthRequest, AuthResponse,
    PairRequest, PairResponse, PairCodeResponse, PairStatusResponse,
    CameraInfo, FallEventResponse, FallEventsListResponse,
    SystemStatusResponse,
)

# ── Google OAuth Client ID ──
# Set this via environment variable or .env file
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

# ── Globals ──
SYSTEM_ID = ""
START_TIME = time.time()
SNAPSHOTS_DIR = os.path.join(PROJECT_ROOT, "fall_snapshots")

# ── Camera Manager Reference ──
# This will be set by the detection system when it starts,
# or we create our own instance for standalone mode.
_camera_manager = None


def get_camera_manager():
    """Get the shared CameraManager instance."""
    global _camera_manager
    if _camera_manager is None:
        try:
            from src.mvc.models.camera_manager import CameraManager
            _camera_manager = CameraManager()
        except Exception as e:
            print(f"⚠️ Could not initialize CameraManager: {e}")
    return _camera_manager


def set_camera_manager(manager):
    """Set the CameraManager instance (called by the detection system)."""
    global _camera_manager
    _camera_manager = manager


# ── Lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    global SYSTEM_ID, START_TIME
    START_TIME = time.time()

    # Initialize database
    init_db()

    # Get or create system ID
    SYSTEM_ID = get_or_create_system_id()
    print(f"🆔 System ID: {SYSTEM_ID}")

    # Generate initial pairing code
    pair_info = create_new_pair_code(SYSTEM_ID)
    print(f"🔗 Pairing code: {pair_info['code']}")

    print(f"🚀 Fall Guard API Server started on http://0.0.0.0:8000")
    yield
    print("👋 Fall Guard API Server stopped")


# ── App ──

app = FastAPI(
    title="Fall Guard API",
    description="API bridge between fall detection system and mobile web app",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow React dev server and local network
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helper: Auth Dependency ──

async def require_auth(request: Request) -> dict:
    """FastAPI dependency that requires a valid JWT."""
    return get_current_user(request)


# ══════════════════════════════════════════
#  AUTH ENDPOINTS
# ══════════════════════════════════════════

@app.post("/api/auth/google", response_model=AuthResponse)
async def auth_google(body: GoogleAuthRequest):
    """Authenticate with Google OAuth2 credential."""
    if not GOOGLE_CLIENT_ID:
        # Development mode: accept any credential and create a test user
        user = upsert_user(
            google_id="dev_user_001",
            email="dev@fallguard.local",
            name="Developer",
            picture=""
        )
        token = create_jwt_token(user["id"], user["email"])
        return AuthResponse(token=token, user=user)

    # Production mode: verify with Google
    user_info = verify_google_token(body.credential, GOOGLE_CLIENT_ID)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid Google credential")

    user = upsert_user(
        google_id=user_info["google_id"],
        email=user_info["email"],
        name=user_info["name"],
        picture=user_info["picture"],
    )

    token = create_jwt_token(user["id"], user["email"])
    return AuthResponse(token=token, user=user)


@app.get("/api/auth/me")
async def auth_me(current_user: dict = Depends(require_auth)):
    """Get current authenticated user info."""
    user = get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ══════════════════════════════════════════
#  PAIRING ENDPOINTS
# ══════════════════════════════════════════

@app.get("/api/pair/generate", response_model=PairCodeResponse)
async def pair_generate():
    """
    Generate a new pairing code.
    Called from the server/admin side — displayed on the Flet desktop app.
    """
    pair_info = create_new_pair_code(SYSTEM_ID)
    return PairCodeResponse(
        code=pair_info["code"],
        expires_in=pair_info["expires_in"],
        system_id=SYSTEM_ID,
    )


@app.get("/api/pair/current")
async def pair_current():
    """Get the current active pairing code (for display on desktop app)."""
    current = get_current_pair_code(SYSTEM_ID)
    if not current:
        # Auto-generate a new one
        pair_info = create_new_pair_code(SYSTEM_ID)
        return PairCodeResponse(
            code=pair_info["code"],
            expires_in=pair_info["expires_in"],
            system_id=SYSTEM_ID,
        )
    return PairCodeResponse(
        code=current["code"],
        expires_in=current["expires_in"],
        system_id=SYSTEM_ID,
    )


@app.post("/api/pair", response_model=PairResponse)
async def pair_device(body: PairRequest, current_user: dict = Depends(require_auth)):
    """Pair the current user with this detection system using a 6-digit code."""
    entry = validate_pair_code(body.code)
    if not entry:
        raise HTTPException(status_code=400, detail="รหัสไม่ถูกต้องหรือหมดอายุแล้ว")

    # Activate pairing in database
    from api_server.database import create_pairing
    pairing = create_pairing(entry["system_id"], body.code)
    result = db_activate_pairing(body.code, current_user["user_id"])

    if not result:
        # Direct DB activation since code was already consumed from in-memory
        from api_server.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        now = time.time()
        cursor.execute(
            """INSERT INTO pairings (user_id, system_id, pair_code, is_active, created_at, paired_at)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (current_user["user_id"], entry["system_id"], body.code, now, now)
        )
        conn.commit()
        conn.close()

    return PairResponse(
        success=True,
        message="จับคู่สำเร็จ!",
        system_id=entry["system_id"],
    )


@app.get("/api/pair/status", response_model=PairStatusResponse)
async def pair_status(current_user: dict = Depends(require_auth)):
    """Check if the current user has an active pairing."""
    pairing = get_active_pairing(current_user["user_id"])
    if pairing:
        return PairStatusResponse(
            is_paired=True,
            system_id=pairing["system_id"],
            paired_at=pairing["paired_at"],
        )
    return PairStatusResponse(is_paired=False)


@app.delete("/api/pair")
async def pair_unpair(current_user: dict = Depends(require_auth)):
    """Unpair the current user."""
    deactivate_pairing(current_user["user_id"])
    return {"success": True, "message": "ยกเลิกการจับคู่แล้ว"}


# ══════════════════════════════════════════
#  CAMERA ENDPOINTS
# ══════════════════════════════════════════

@app.get("/api/cameras")
async def list_cameras(current_user: dict = Depends(require_auth)):
    """List all active and registered cameras."""
    manager = get_camera_manager()
    if not manager:
        return []

    cameras = []
    # ยูเนียนกล้องทั้งหมดจากประวัติการทำงานและที่บันทึกใน config/cameras.json
    all_ips = set(manager.active_cameras.keys()) | set(manager.camera_names.keys())
    for ip in all_ips:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            continue
            
        is_active = manager.active_cameras.get(ip, False)
        cameras.append(CameraInfo(
            ip=ip,
            name=manager.camera_names.get(ip, ip),
            has_frame=is_active and (ip in manager.frame_buffer),
        ))
    return cameras


@app.get("/api/frames")
async def get_all_frames(current_user: dict = Depends(require_auth)):
    """Get base64 JPEG frames from all active cameras."""
    manager = get_camera_manager()
    if not manager:
        return {}

    return dict(manager.frame_buffer)


@app.get("/api/frames/{ip}")
async def get_single_frame(ip: str, current_user: dict = Depends(require_auth)):
    """Get base64 JPEG frame from a specific camera."""
    manager = get_camera_manager()
    if not manager or ip not in manager.frame_buffer:
        raise HTTPException(status_code=404, detail="Camera not found or no frame available")

    return {"ip": ip, "frame": manager.frame_buffer[ip]}


@app.get("/api/stream/{ip}")
async def video_stream(ip: str):
    """MJPEG stream endpoint for real-time video without base64 overhead."""
    manager = get_camera_manager()
    if not manager or not manager.active_cameras.get(ip, False):
        raise HTTPException(status_code=404, detail="Camera not found or inactive")

    async def frame_generator():
        last_frame_data = None
        while True:
            # ตรวจสอบว่ากล้องยังเปิดอยู่ไหม
            if not manager.active_cameras.get(ip, False):
                break
                
            frame_data = manager.frame_buffer.get(ip)
            # ส่งเฟรมใหม่เมื่อมีการเปลี่ยนแปลงเท่านั้น
            if frame_data and frame_data != last_frame_data:
                last_frame_data = frame_data
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
            
            # หน่วงเวลาเล็กน้อยลดการใช้ CPU ของ loop (ประมาณ 30fps)
            await asyncio.sleep(0.033)

    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


# ══════════════════════════════════════════
#  FALL EVENTS ENDPOINTS
# ══════════════════════════════════════════

@app.get("/api/fall-events", response_model=FallEventsListResponse)
async def list_fall_events(
    limit: int = 50,
    offset: int = 0,
    camera: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    current_user: dict = Depends(require_auth),
):
    """
    Get fall events with optional filters.
    date_from/date_to format: YYYY-MM-DD
    """
    from_ts = None
    to_ts = None

    if date_from:
        try:
            from_ts = datetime.strptime(date_from, "%Y-%m-%d").timestamp()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format (use YYYY-MM-DD)")

    if date_to:
        try:
            to_ts = datetime.strptime(date_to, "%Y-%m-%d").timestamp() + 86400  # End of day
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format (use YYYY-MM-DD)")

    events = get_fall_events(
        limit=limit, offset=offset,
        camera_ip=camera,
        date_from=from_ts, date_to=to_ts,
    )

    response_events = []
    for e in events:
        detected_dt = datetime.fromtimestamp(e["detected_at"])
        response_events.append(FallEventResponse(
            id=e["id"],
            camera_ip=e["camera_ip"],
            camera_name=e["camera_name"],
            snapshot_filename=e["snapshot_filename"],
            snapshot_url=f"/api/snapshots/{e['snapshot_filename']}" if e["snapshot_filename"] else None,
            detected_at=e["detected_at"],
            detected_at_formatted=detected_dt.strftime("%d/%m/%Y %H:%M:%S"),
            duration_seconds=e["duration_seconds"],
        ))

    return FallEventsListResponse(events=response_events, total=len(response_events))


@app.get("/api/snapshots/{filename}")
async def get_snapshot(filename: str):
    """Serve a fall snapshot image."""
    filepath = os.path.join(SNAPSHOTS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return FileResponse(filepath, media_type="image/jpeg")


# ══════════════════════════════════════════
#  STATUS ENDPOINT
# ══════════════════════════════════════════

@app.get("/api/status", response_model=SystemStatusResponse)
async def system_status():
    """System health check — no auth required."""
    manager = get_camera_manager()
    active_count = 0
    if manager:
        active_count = sum(1 for v in manager.active_cameras.values() if v)

    return SystemStatusResponse(
        status="online",
        cameras_active=active_count,
        system_id=SYSTEM_ID,
        uptime_seconds=round(time.time() - START_TIME, 1),
    )


# ══════════════════════════════════════════
#  STATIC FILE SERVING (Production)
# ══════════════════════════════════════════

# Mount React build directory LAST (catch-all)
WEB_DIST = os.path.join(PROJECT_ROOT, "web_app", "dist")
if os.path.isdir(WEB_DIST):
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=os.path.join(WEB_DIST, "assets")), name="assets")

    # Catch-all: serve index.html for SPA routing
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA — all non-API routes get index.html."""
        # Don't intercept API routes
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        
        index_path = os.path.join(WEB_DIST, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Web app not built yet. Run 'npm run build' in web_app/")


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api_server.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
