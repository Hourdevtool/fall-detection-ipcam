---
name: fall-guard-ipcam
description: ระบบ Fall Detection จากกล้อง IP Camera ผ่าน ONVIF พร้อม Web App สำหรับดูผ่านมือถือ
---

# Fall Guard — IP Camera Fall Detection System

## ภาพรวมโปรเจค

ระบบตรวจจับการล้มของผู้สูงอายุจากกล้อง IP Camera ผ่าน ONVIF/RTSP โดยมี 3 ส่วนหลัก:

1. **Desktop Detection App** (Flet) — สแกน LAN หากล้อง ONVIF, ดึง RTSP stream, รัน AI ตรวจจับการล้ม (YOLOv8 + Random Forest)
2. **API Server** (FastAPI) — เป็น bridge ระหว่าง detection system กับ web app, จัดการ auth/pairing/fall events
3. **Mobile Web App** (React + Vite) — SPA สำหรับดูภาพกล้อง live + ประวัติการล้มผ่านมือถือ

## สถาปัตยกรรม

```
d:\buff_p\
├── main.py                    # Entry point — Flet desktop app
├── detection.py               # FallDetector: YOLOv8 + RF model + fall callback
├── config.json                # ONVIF credentials (username/password)
├── cameras.json               # Camera names {ip: name}
├── Tools/                     # AI models (yolov8n-pose.pt, fall_detect_model.pkl)
├── fall_snapshots/            # JPEG snapshots ขณะตรวจพบการล้ม
│
├── src/
│   ├── services/
│   │   └── playvideo.py       # RTSP stream reader + AI processing + fall logging
│   └── mvc/
│       ├── controllers/
│       │   └── main_controller.py  # จัดการ camera scanning + frame updates
│       ├── models/
│       │   ├── camera_manager.py   # จัดการ streams, frame_buffer (base64)
│       │   └── network_scanner.py  # สแกน LAN หากล้อง ONVIF
│       └── views/
│           └── main_view.py   # Flet UI (camera grid + dialogs)
│
├── api_server/                # FastAPI backend
│   ├── server.py              # App + CORS + static mount + startup/shutdown
│   ├── database.py            # SQLite (users, pairings, fall_events)
│   ├── auth.py                # Google OAuth2 verify + JWT tokens
│   ├── models.py              # Pydantic request/response schemas
│   ├── pairing.py             # 6-digit code generation + validation
│   └── fall_logger.py         # บันทึก fall events + snapshots to disk
│
└── web_app/                   # React + Vite SPA
    ├── vite.config.js         # proxy /api → localhost:8000
    ├── src/
    │   ├── main.jsx           # Entry + GoogleOAuthProvider + BrowserRouter
    │   ├── App.jsx            # Routes + ProtectedRoute
    │   ├── index.css          # Design system (CSS variables, dark theme)
    │   ├── pages/
    │   │   ├── LoginPage.jsx      # Google Sign-in
    │   │   ├── PairPage.jsx       # 6-digit code input
    │   │   ├── DashboardPage.jsx  # Live camera feed grid
    │   │   └── HistoryPage.jsx    # Fall events timeline
    │   ├── components/
    │   │   ├── BottomNav.jsx      # Mobile tab bar
    │   │   ├── CameraCard.jsx     # Glassmorphism live feed card
    │   │   ├── FallEventCard.jsx  # Fall event + snapshot card
    │   │   ├── LiveBadge.jsx      # ● LIVE pulse
    │   │   ├── StatusChip.jsx     # Normal / Fall status
    │   │   ├── PairCodeInput.jsx  # OTP-style 6-digit input
    │   │   └── ProtectedRoute.jsx # Auth guard
    │   ├── hooks/
    │   │   ├── useAuth.js         # Auth state management
    │   │   └── useCameraFeed.js   # Polling /api/frames
    │   ├── lib/
    │   │   └── api.js             # fetch wrapper + auth headers
    │   └── contexts/
    │       └── AuthContext.jsx    # React Context for auth
    └── dist/                  # Production build → served by FastAPI

```

## เทคโนโลยี

### Desktop App (เดิม)
- **Python 3.13+**, **Flet** (UI framework)
- **YOLOv8** (pose estimation) + **scikit-learn** Random Forest (fall classification)
- **PyAV** (RTSP stream decode), **OpenCV** (image processing)
- **onvif-zeep** (ONVIF camera discovery)
- **edge-tts** + **pygame** (TTS alert)

### API Server (ใหม่)
- **FastAPI** + **uvicorn**
- **SQLite** (aiosqlite) — เก็บ metadata เท่านั้น, ภาพเก็บเป็นไฟล์
- **google-auth** — verify Google ID token
- **PyJWT** — session tokens
- **qrcode** — QR code generation
- **python-multipart** — file uploads

### Web App (ใหม่)
- **React 19** + **Vite**
- **react-router-dom v7** — SPA routing
- **@react-oauth/google** — Google Sign-in (ไม่ใช้ Firebase)
- **framer-motion** — animations
- **jwt-decode** — decode JWT client-side

## Data Flow สำคัญ

### Live Camera Feed
```
กล้อง ONVIF → RTSP → PyAV decode → OpenCV resize → YOLO+RF detection
→ cv2.imencode JPEG → base64 → frame_buffer dict
→ API GET /api/frames → React polling ทุก 1-2 วินาที → <img src={base64}>
```

### Fall Event Logging
```
FallDetector.process_frame() → fall_counter >= fall_trigger_frames
→ on_fall_callback(camera_name, frame, timestamp)
→ cv2.imwrite() → fall_snapshots/{timestamp}_{ip}.jpg
→ INSERT INTO fall_events (camera_ip, camera_name, snapshot_filename, detected_at)
→ Web App GET /api/fall-events → Timeline display
→ <img src="/api/snapshots/{filename}"> → ภาพ snapshot
```

### Pairing Flow
```
API Server start → generate system_id (UUID, stored in DB)
Admin เห็น pairing code บน Flet desktop app / API endpoint
User login Google → กรอก 6-digit code → POST /api/pair
→ Validate code + expiry → INSERT pairing (user_id ↔ system_id)
→ ครั้งต่อไป login → check pairing exists → skip pair page
```

### Auth Flow (No Firebase)
```
React: @react-oauth/google → Google ID token (credential)
→ POST /api/auth/google {credential}
→ FastAPI: google.oauth2.id_token.verify_oauth2_token()
→ Extract email, name, picture → upsert users table
→ Sign JWT {user_id, email} → return to React
→ React: localStorage.setItem("token", jwt)
→ ทุก API call: Authorization: Bearer {jwt}
```

## Design System — "Midnight Luxury"

- **Theme**: Dark-only, glassmorphism
- **Font**: Inter (Google Fonts)
- **Primary BG**: `#08080d`
- **Card BG**: `#111118`
- **Accent**: `#6c63ff` (Indigo-Purple)
- **Success/Live**: `#00d4aa` (Teal)
- **Danger/Fall**: `#ff4757` (Red)
- **Gradient**: `linear-gradient(135deg, #6c63ff, #00d4aa)`
- **Glass**: `rgba(255,255,255,0.04)` + `backdrop-filter: blur(20px)`

## Deployment

### Development
```bash
# Terminal 1: API Server
cd d:\buff_p && python -m api_server.server

# Terminal 2: React Dev Server (hot reload)
cd d:\buff_p\web_app && npm run dev
```

### Production (Option C — แนะนำ)
```bash
# Build React
cd d:\buff_p\web_app && npm run build

# FastAPI serves everything on port 8000
cd d:\buff_p && python -m api_server.server
# React build at /web_app/dist → mounted as static files
# API at /api/*
# Access: http://<local-ip>:8000
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/auth/google | — | Google credential → JWT |
| GET | /api/auth/me | ✅ | Current user info |
| POST | /api/pair | ✅ | Pair user with system |
| GET | /api/pair/generate | — | Generate new pairing code (server-side) |
| GET | /api/pair/status | ✅ | Check if user is paired |
| GET | /api/cameras | ✅ | Active cameras list |
| GET | /api/frames | ✅ | All camera frames (base64) |
| GET | /api/frames/{ip} | ✅ | Single camera frame |
| GET | /api/fall-events | ✅ | Fall history (?date=&camera=&limit=) |
| GET | /api/snapshots/{filename} | ✅ | Serve snapshot JPEG |
| GET | /api/status | — | System health check |

## SQLite Schema

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    google_id TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    name TEXT,
    picture TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pairings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    system_id TEXT NOT NULL,
    pair_code TEXT,
    is_active BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    paired_at TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE TABLE fall_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_ip TEXT NOT NULL,
    camera_name TEXT,
    snapshot_filename TEXT,
    detected_at TIMESTAMP NOT NULL,
    duration_seconds REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## สิ่งที่ต้องเตรียม

1. **Google Cloud Console** → สร้าง OAuth 2.0 Client ID (Web application)
   - Authorized JavaScript origins: `http://localhost:5173`, `http://<local-ip>:8000`
   - ได้ Client ID มาใส่ใน React app (.env)
2. **Python packages เพิ่ม**: `fastapi uvicorn aiosqlite google-auth pyjwt qrcode python-multipart pillow`
3. **Node.js 18+** สำหรับ React dev

## Conventions

- ภาษาไทยใน UI, ภาษาอังกฤษใน code
- CSS variables สำหรับ design tokens ทั้งหมด
- API responses เป็น JSON เสมอ
- Error responses: `{"detail": "error message"}`
- JWT expiry: 7 วัน
- Pairing code expiry: 10 นาที
- Fall event cooldown: 30 วินาที (ป้องกัน duplicate)
- Frame polling interval: 1.5 วินาที
