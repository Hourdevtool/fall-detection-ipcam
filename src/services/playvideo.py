import av
import cv2
import base64
import numpy as np
import json
import os
import threading
import time
from detection import FallDetector

# --- TurboJPEG (fast SIMD-optimized JPEG encoder) with fallback ---
_turbojpeg_instance = None
_turbojpeg_available = False
try:
    from turbojpeg import TurboJPEG

    # ลองเปิดแบบ auto-detect ก่อน
    try:
        _turbojpeg_instance = TurboJPEG()
    except RuntimeError:
        # Windows: ลองหา DLL จาก path ที่ libjpeg-turbo ติดตั้ง
        _win_paths = [
            r"C:\libjpeg-turbo64\bin\turbojpeg.dll",
            r"C:\Program Files\libjpeg-turbo\bin\turbojpeg.dll",
            r"C:\Program Files\libjpeg-turbo64\bin\turbojpeg.dll",
        ]
        for p in _win_paths:
            if os.path.exists(p):
                _turbojpeg_instance = TurboJPEG(lib_path=p)
                break

    if _turbojpeg_instance is not None:
        _turbojpeg_available = True
        print("🚀 TurboJPEG loaded — JPEG encoding will be 2-5x faster")
    else:
        print("⚠️ TurboJPEG library not found, falling back to cv2.imencode")
except ImportError:
    print("⚠️ PyTurboJPEG not installed, falling back to cv2.imencode")


def _encode_jpeg(frame, quality=50):
    """Encode frame to JPEG bytes using TurboJPEG (fast) or cv2 (fallback)."""
    if _turbojpeg_available and _turbojpeg_instance is not None:
        return _turbojpeg_instance.encode(frame, quality=quality)
    else:
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buffer.tobytes()


# 🚀 OPTIMIZATION: Singleton FallDetector — โหลด YOLO/RF ครั้งเดียว แชร์ทุกกล้อง
_shared_detector = None
_detector_lock = threading.Lock()

def _get_shared_detector(on_fall_callback=None, on_intruder_callback=None):
    """Get or create the shared FallDetector instance (thread-safe singleton)."""
    global _shared_detector
    if _shared_detector is None:
        with _detector_lock:
            if _shared_detector is None:
                print("🧠 Loading shared AI models (YOLO + Random Forest)...")
                _shared_detector = FallDetector(on_fall_callback=on_fall_callback, on_intruder_callback=on_intruder_callback)
                print("✅ Shared AI models loaded successfully!")
    # Update callback if provided (each camera may have its own logging callback)
    if on_fall_callback is not None:
        _shared_detector.on_fall_callback = on_fall_callback
    if on_intruder_callback is not None:
        _shared_detector.on_intruder_callback = on_intruder_callback
    return _shared_detector


# ═══════════════════════════════════════════════════════════════════════════════
#  Low-latency PyAV connection options
# ═══════════════════════════════════════════════════════════════════════════════

# Each dict is tried in order: plain → TCP → UDP
_AV_OPTIONS_LIST = [
    {
        'stimeout': '5000000',
        'fflags': 'nobuffer',          # ไม่ buffer — ลด latency
        'flags': 'low_delay',          # ลด delay ของ decoder
    },
    {
        'rtsp_transport': 'tcp',
        'stimeout': '5000000',
        'fflags': 'nobuffer',
        'flags': 'low_delay',
    },
    {
        'rtsp_transport': 'udp',
        'stimeout': '5000000',
        'fflags': 'nobuffer',
        'flags': 'low_delay',
    },
]


def _open_stream(ip, rtsp_url):
    """Try to open RTSP stream with multiple transport options.
    
    Returns (container, protocol_name) or (None, None) if all fail.
    Enables FFmpeg multi-threaded decoding for better performance.
    """
    for opts in _AV_OPTIONS_LIST:
        proto = opts.get('rtsp_transport', 'auto').upper()
        try:
            container = av.open(rtsp_url, 'r', options=opts)

            # 🚀 Enable FFmpeg multi-threaded decoding
            for stream in container.streams.video:
                stream.thread_type = 'AUTO'  # ใช้ slice + frame threading

            # ลอง decode 1 เฟรมเพื่อตรวจสอบว่าสตรีมใช้ได้จริง
            test_frame = None
            for f in container.decode(video=0):
                test_frame = f
                break

            if test_frame is not None:
                print(f"✅ [สตรีม] IP: {ip} เชื่อมต่อสำเร็จด้วย {proto}")
                return container, proto
            else:
                container.close()
                print(f"⚠️ [สตรีม] IP: {ip} ลอง {proto}: เปิดได้แต่ไม่มีเฟรม")
        except Exception as e:
            print(f"⚠️ [สตรีม] IP: {ip} ลอง {proto} ไม่สำเร็จ: {type(e).__name__}: {e}")

    return None, None


# ═══════════════════════════════════════════════════════════════════════════════
#  Main streaming function with auto-reconnect
# ═══════════════════════════════════════════════════════════════════════════════

# Reconnect settings
_MAX_RETRIES = 5
_BASE_BACKOFF_SEC = 2  # exponential: 2s → 4s → 8s → 16s → 32s


def play_stream_pyav(ip, rtsp_url, active_cameras, frame_buffer, camera_names, frame_buffer_b64=None):
    """Stream video from RTSP with auto-reconnect, TurboJPEG, and double-buffering."""
    print(f"🎬 [เริ่มดึงภาพ] IP: {ip} (ด้วย PyAV + optimizations)")

    # Load camera name from config/cameras.json or shared dict
    if camera_names is None:
        camera_names = {}
        try:
            if os.path.exists("config/cameras.json"):
                with open("config/cameras.json", "r", encoding="utf-8") as f:
                    camera_names = json.load(f)
        except Exception as e:
            print(f"⚠️ Error reading cameras.json: {e}")

    camera_name = camera_names.get(ip, ip)

    # Fall event logging callback
    def _on_fall(cam_name, frame, timestamp):
        try:
            from api_server.fall_logger import log_fall_event
            log_fall_event(ip, cam_name, frame, timestamp)
        except Exception as e:
            print(f"⚠️ Fall logging error: {e}")

    # Intruder event logging callback
    def _on_intruder(cam_name, frame, timestamp):
        try:
            from api_server.fall_logger import log_intruder_event
            log_intruder_event(ip, cam_name, frame, timestamp)
        except Exception as e:
            print(f"⚠️ Intruder logging error: {e}")

    # 🚀 OPTIMIZATION: ใช้ FallDetector ตัวเดียวกันทุกกล้อง (ลด RAM ~500MB ต่อกล้อง)
    detector = _get_shared_detector(on_fall_callback=_on_fall, on_intruder_callback=_on_intruder)

    # ─── Auto-reconnect loop ─────────────────────────────────────────────
    retry_count = 0

    while active_cameras.get(ip, False) and retry_count < _MAX_RETRIES:
        if retry_count > 0:
            backoff = _BASE_BACKOFF_SEC * (2 ** (retry_count - 1))
            print(f"🔄 [Reconnect] IP: {ip} — รอ {backoff}s ก่อน retry ({retry_count}/{_MAX_RETRIES})...")
            # Sleep with early exit check
            for _ in range(int(backoff * 10)):
                if not active_cameras.get(ip, False):
                    print(f"🛑 [Reconnect] IP: {ip} — ถูกยกเลิกระหว่างรอ")
                    _cleanup(ip, frame_buffer, frame_buffer_b64)
                    return
                time.sleep(0.1)

        # Try to open the stream
        container, proto = _open_stream(ip, rtsp_url)
        if container is None:
            print(f"❌ [สตรีม] IP: {ip} ไม่สามารถเชื่อมต่อสตรีมได้ (attempt {retry_count + 1})")
            retry_count += 1
            continue

        # ✅ Connected — reset retry counter
        retry_count = 0

        # Run the streaming pipeline (returns when stream dies)
        stream_ok = _run_stream_pipeline(
            ip, container, detector, camera_names, camera_name,
            active_cameras, frame_buffer, frame_buffer_b64,
        )

        # Close the container
        try:
            container.close()
        except Exception:
            pass

        if not stream_ok and active_cameras.get(ip, False):
            # Stream died but camera is still supposed to be active → reconnect
            retry_count += 1
            print(f"⚠️ [สตรีม] IP: {ip} — stream ขาด, จะ reconnect...")
        else:
            # Either clean exit or camera was deactivated
            break

    if retry_count >= _MAX_RETRIES:
        print(f"❌ [สตรีม] IP: {ip} — reconnect ครบ {_MAX_RETRIES} ครั้งแล้ว หยุดสตรีม")

    _cleanup(ip, frame_buffer, frame_buffer_b64)
    active_cameras[ip] = False
    print(f"🛑 [ปิดสตรีม] IP: {ip}")


def _cleanup(ip, frame_buffer, frame_buffer_b64):
    """Remove frame buffers for a camera."""
    if ip in frame_buffer:
        del frame_buffer[ip]
    if frame_buffer_b64 is not None and ip in frame_buffer_b64:
        del frame_buffer_b64[ip]


def _run_stream_pipeline(ip, container, detector, camera_names, camera_name,
                         active_cameras, frame_buffer, frame_buffer_b64):
    """Run the 3-thread streaming pipeline (reader → AI → display).
    
    Returns True if exited cleanly, False if stream died unexpectedly.
    """

    # ─── Shared state ────────────────────────────────────────────────────
    # Double-buffer: AI writes to write_buf, display reads from read_buf
    # Lock-free swap via list index toggle
    _double_buf = [None, None]  # [read_idx_frame, write_idx_frame]
    _buf_idx = [0]              # current read index (0 or 1)

    latest_frame = [None]       # raw frame from reader (always the newest)
    last_frame_time = [time.time()]
    running = [True]
    stream_died = [False]       # True if stream ended unexpectedly
    heartbeat_time = [time.time()]

    # ─── Reader thread ───────────────────────────────────────────────────
    def read_frames():
        try:
            for frame in container.decode(video=0):  # type: ignore
                if not running[0] or not active_cameras.get(ip, False):
                    break
                latest_frame[0] = frame.to_ndarray(format="bgr24")
                last_frame_time[0] = time.time()
        except av.error.EOFError:
            print(f"📡 [Reader] IP: {ip} → stream EOF (จบสตรีม)")
            stream_died[0] = True
        except Exception as e:
            print(f"❌ [Reader] IP: {ip} → {type(e).__name__}: {e}")
            stream_died[0] = True
        finally:
            running[0] = False

    reader_thread = threading.Thread(target=read_frames, daemon=True, name=f"Reader-{ip}")
    reader_thread.start()

    # ─── AI thread (double-buffer write) ─────────────────────────────────
    ai_interval_sec = 0.15  # ~6-7 FPS สำหรับ AI

    def ai_worker():
        """รัน AI inference แยก thread — เขียนผลลัพธ์ลง double-buffer"""
        while running[0] and active_cameras.get(ip, False):
            frame_img = latest_frame[0]
            if frame_img is not None:
                cam_name = camera_names.get(ip, camera_name)
                try:
                    # Resize สำหรับ AI (640x360 เพื่อความแม่นยำ)
                    img_for_ai = cv2.resize(frame_img, (640, 360), interpolation=cv2.INTER_LINEAR)
                    processed = detector.process_frame(img_for_ai, cam_name)

                    # Double-buffer swap: เขียนลง write slot แล้วสลับ index
                    write_idx = 1 - _buf_idx[0]
                    _double_buf[write_idx] = processed
                    _buf_idx[0] = write_idx  # atomic int swap — ไม่ต้องใช้ lock

                except Exception as e:
                    print(f"⚠️ [AI] IP: {ip} → {type(e).__name__}: {e}")
            time.sleep(ai_interval_sec)

    ai_thread = threading.Thread(target=ai_worker, daemon=True, name=f"AI-{ip}")
    ai_thread.start()

    # ─── Display loop (reads from double-buffer, encodes JPEG) ───────────
    try:
        while running[0] and active_cameras.get(ip, False):
            now = time.time()

            # ── Stream health check ──
            stall_duration = now - last_frame_time[0]
            if stall_duration > 8.0:
                print(f"⚠️ [Display] IP: {ip} → ไม่ได้รับเฟรมใหม่เกิน {stall_duration:.1f}s (สตรีมค้าง)")
                stream_died[0] = True
                running[0] = False
                break

            # ── Heartbeat log ทุก 60 วินาที ──
            if now - heartbeat_time[0] > 60.0:
                heartbeat_time[0] = now
                print(f"💚 [Heartbeat] IP: {ip} — streaming OK ({stall_duration:.1f}s since last frame)")

            # ── Read raw frame for smooth 30 FPS display ──
            raw = latest_frame[0]
            display_frame = None

            if raw is not None:
                cam_name = camera_names.get(ip, camera_name)
                display_frame = cv2.resize(raw, (640, 360), interpolation=cv2.INTER_LINEAR)
                display_frame = detector.draw_overlay(display_frame, cam_name)

            if display_frame is not None:
                # 🚀 Encode JPEG with TurboJPEG (or cv2 fallback)
                jpeg_bytes = _encode_jpeg(display_frame, quality=50)

                # เก็บ raw JPEG bytes สำหรับ MJPEG web stream
                frame_buffer[ip] = jpeg_bytes

                # 🚀 Pre-encode base64 สำหรับ Flet UI (ไม่ต้องทำใน UI thread)
                if frame_buffer_b64 is not None:
                    frame_buffer_b64[ip] = base64.b64encode(jpeg_bytes).decode('utf-8')

            # 🚀 ~30 FPS display rate
            time.sleep(0.033)

    except Exception as e:
        print(f"❌ [Display] IP: {ip} → {type(e).__name__}: {e}")
        stream_died[0] = True
    finally:
        running[0] = False

    # Wait for threads to finish (with timeout)
    reader_thread.join(timeout=3.0)
    ai_thread.join(timeout=2.0)

    return not stream_died[0]
