import av
import cv2
import base64
import numpy as np
import json
import os
import threading
import time
from detection import FallDetector
from src.services.frame_splitter import FrameSplitter

# --- TurboJPEG (fast SIMD-optimized JPEG encoder) with fallback ---
_turbojpeg_instance = None
_turbojpeg_available = False
try:
    from turbojpeg import TurboJPEG
    try:
        _turbojpeg_instance = TurboJPEG()
    except RuntimeError:
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
except ImportError:
    pass


def _encode_jpeg(frame, quality=75):
    """Encode frame to JPEG bytes with high visual clarity."""
    if _turbojpeg_available and _turbojpeg_instance is not None:
        return _turbojpeg_instance.encode(frame, quality=quality)
    else:
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buffer.tobytes()


_shared_detector = None
_detector_lock = threading.Lock()

def _get_shared_detector(on_fall_callback=None, on_intruder_callback=None):
    global _shared_detector
    if _shared_detector is None:
        with _detector_lock:
            if _shared_detector is None:
                print("🧠 Loading shared AI models (YOLO + Random Forest)...")
                _shared_detector = FallDetector(on_fall_callback=on_fall_callback, on_intruder_callback=on_intruder_callback)
                print("✅ Shared AI models loaded successfully!")
    if on_fall_callback is not None:
        _shared_detector.on_fall_callback = on_fall_callback
    if on_intruder_callback is not None:
        _shared_detector.on_intruder_callback = on_intruder_callback
    return _shared_detector


# PyAV connection options — AUTO first (กล้องส่วนใหญ่ค้างถ้าบังคับ TCP/UDP)
_AV_OPTIONS_LIST = [
    {'stimeout': '2000000'},                                  # Auto (เร็วที่สุด)
    {'rtsp_transport': 'tcp', 'stimeout': '2000000'},         # TCP fallback
    {'rtsp_transport': 'udp', 'stimeout': '2000000'},         # UDP fallback
]


def _open_stream(ip, rtsp_url):
    """Try to open RTSP stream — ลอง URL จาก ONVIF ก่อน แล้วค่อยลอง fallback."""
    import re
    user = "admin"
    password = ""
    port = "554"

    m = re.match(r'rtsp://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?(.*)', rtsp_url)
    if m:
        user = m.group(1)
        password = m.group(2)
        ip = m.group(3)
        port = m.group(4) or "554"

    # ลอง URL จาก ONVIF ก่อน (เป็น URL ที่ถูกต้องที่สุด) แล้วค่อยลอง fallback
    candidate_urls = [
        rtsp_url,
        f"rtsp://{user}:{password}@{ip}:{port}/onvif1",
        f"rtsp://{user}:{password}@{ip}:{port}/onvif2",
        f"rtsp://{ip}:{port}/onvif1",
        f"rtsp://{user}:{password}@{ip}:{port}/user={user}&password={password}&channel=1&stream=0.sdp",
        f"rtsp://{user}:{password}@{ip}:{port}/user={user}&password={password}&channel=1&stream=1.sdp",
        f"rtsp://{user}:{password}@{ip}:{port}/live/ch0",
    ]

    # Remove duplicates
    seen = set()
    unique = [u for u in candidate_urls if u and u not in seen and not seen.add(u)]

    for candidate in unique:
        for opts in _AV_OPTIONS_LIST:
            proto = opts.get('rtsp_transport', 'auto').upper()
            try:
                container = av.open(candidate, 'r', options=opts)
                if container.streams.video:
                    print(f"✅ [สตรีม] IP: {ip} เชื่อมต่อสำเร็จด้วย {proto} ({candidate})")
                    return container, proto
                else:
                    container.close()
            except Exception:
                pass

    print(f"❌ [สตรีม] IP: {ip} ไม่สามารถเชื่อมต่อ RTSP ได้")
    return None, None


_MAX_RETRIES = 10
_BASE_BACKOFF_SEC = 2


def play_stream_pyav(ip, rtsp_url, active_cameras, frame_buffer, camera_names, frame_buffer_b64=None, camera_config=None):
    print(f"🎬 [เริ่มดึงภาพ] IP: {ip}")

    if camera_names is None:
        camera_names = {}
        try:
            if os.path.exists("config/cameras.json"):
                with open("config/cameras.json", "r", encoding="utf-8") as f:
                    camera_names = json.load(f)
        except Exception as e:
            pass

    camera_name = camera_names.get(ip, ip)

    def _on_fall(cam_name, frame, timestamp):
        try:
            from api_server.fall_logger import log_fall_event
            log_fall_event(ip, cam_name, frame, timestamp)
        except Exception as e:
            print(f"⚠️ Fall logging error: {e}")

    def _on_intruder(cam_name, frame, timestamp):
        try:
            from api_server.fall_logger import log_intruder_event
            log_intruder_event(ip, cam_name, frame, timestamp)
        except Exception as e:
            print(f"⚠️ Intruder logging error: {e}")

    detector = _get_shared_detector(on_fall_callback=_on_fall, on_intruder_callback=_on_intruder)

    retry_count = 0

    while active_cameras.get(ip, False) and retry_count < _MAX_RETRIES:
        if retry_count > 0:
            backoff = min(10, _BASE_BACKOFF_SEC * retry_count)
            print(f"🔄 [Reconnect] IP: {ip} — รอ {backoff}s ก่อน retry ({retry_count}/{_MAX_RETRIES})...")
            for _ in range(int(backoff * 10)):
                if not active_cameras.get(ip, False):
                    _cleanup(ip, frame_buffer, frame_buffer_b64)
                    return
                time.sleep(0.1)

        container, proto = _open_stream(ip, rtsp_url)
        if container is None:
            retry_count += 1
            continue

        retry_count = 0

        stream_ok = _run_stream_pipeline(
            ip, container, detector, camera_names, camera_name,
            active_cameras, frame_buffer, frame_buffer_b64,
            camera_config=camera_config,
        )

        try:
            container.close()
        except Exception:
            pass

        if not stream_ok and active_cameras.get(ip, False):
            retry_count += 1
        else:
            break

    _cleanup(ip, frame_buffer, frame_buffer_b64)
    active_cameras[ip] = False
    print(f"🛑 [ปิดสตรีม] IP: {ip}")


def _cleanup(ip, frame_buffer, frame_buffer_b64):
    if ip in frame_buffer:
        del frame_buffer[ip]
    if frame_buffer_b64 is not None and ip in frame_buffer_b64:
        del frame_buffer_b64[ip]


def _run_stream_pipeline(ip, container, detector, camera_names, camera_name,
                         active_cameras, frame_buffer, frame_buffer_b64,
                         camera_config=None):
    splitter = FrameSplitter(camera_config)

    latest_frame = [None]
    last_frame_time = [time.time()]
    running = [True]
    stream_died = [False]
    heartbeat_time = [time.time()]

    # ─── Reader thread (grabs fresh frames directly from RTSP) ───────────
    def read_frames():
        consecutive_errors = 0
        try:
            if not container.streams.video:
                stream_died[0] = True
                return
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            for packet in container.demux(stream):
                if not running[0] or not active_cameras.get(ip, False):
                    break
                if packet.dts is None:
                    continue
                try:
                    for frame in packet.decode():
                        latest_frame[0] = frame.to_ndarray(format="bgr24")
                        last_frame_time[0] = time.time()
                        consecutive_errors = 0
                except Exception:
                    consecutive_errors += 1
                    if consecutive_errors > 100:
                        stream_died[0] = True
                        break
        except av.error.EOFError:
            stream_died[0] = True
        except Exception as e:
            print(f"⚠️ [สตรีม {ip}] RTSP stream ended: {e}")
            stream_died[0] = True
        finally:
            running[0] = False

    reader_thread = threading.Thread(target=read_frames, daemon=True, name=f"Reader-{ip}")
    reader_thread.start()

    # ─── AI thread (optimized: alternates sub-frames to cut CPU in half) ─
    ai_interval_sec = 0.08  # ~12 FPS AI inference

    def ai_worker():
        tick = 0
        while running[0] and active_cameras.get(ip, False):
            frame_img = latest_frame[0]
            if frame_img is not None:
                cam_name = camera_names.get(ip, camera_name)
                try:
                    sub_frames = splitter.split_frame(frame_img)
                    
                    if len(sub_frames) > 1:
                        # Process both subframes efficiently
                        for idx, (label, sub_frame) in enumerate(sub_frames):
                            sub_id = f"{ip}_{label}"
                            sub_name = f"{cam_name} ({label})"
                            detector.process_frame(sub_frame, sub_name, camera_id=sub_id)
                    else:
                        label, sub_frame = sub_frames[0]
                        detector.process_frame(sub_frame, cam_name, camera_id=ip)

                    tick += 1
                except Exception as e:
                    pass
            time.sleep(ai_interval_sec)

    ai_thread = threading.Thread(target=ai_worker, daemon=True, name=f"AI-{ip}")
    ai_thread.start()

    # ─── Display loop (smooth 30 FPS, crisp 960x540 resolution) ──────────
    DISPLAY_W = 960
    DISPLAY_H = 540

    try:
        while running[0] and active_cameras.get(ip, False):
            now = time.time()

            stall_duration = now - last_frame_time[0]
            if stall_duration > 10.0:
                stream_died[0] = True
                running[0] = False
                break

            if now - heartbeat_time[0] > 60.0:
                heartbeat_time[0] = now

            raw = latest_frame[0]
            display_frame = None

            if raw is not None:
                cam_name = camera_names.get(ip, camera_name)
                sub_frames = splitter.split_frame(raw)

                if len(sub_frames) > 1:
                    sub_h = DISPLAY_H // len(sub_frames)
                    parts = []
                    for label, sf in sub_frames:
                        sub_id = f"{ip}_{label}"
                        sub_name = f"{cam_name} ({label})"
                        resized = cv2.resize(sf, (DISPLAY_W, sub_h), interpolation=cv2.INTER_LINEAR)
                        overlaid = detector.draw_overlay(resized, sub_name, camera_id=sub_id)
                        parts.append(overlaid)
                    display_frame = np.vstack(parts)
                else:
                    display_frame = cv2.resize(raw, (DISPLAY_W, DISPLAY_H), interpolation=cv2.INTER_LINEAR)
                    display_frame = detector.draw_overlay(display_frame, cam_name, camera_id=ip)

            if display_frame is not None:
                jpeg_bytes = _encode_jpeg(display_frame, quality=75)
                frame_buffer[ip] = jpeg_bytes

                if frame_buffer_b64 is not None:
                    frame_buffer_b64[ip] = base64.b64encode(jpeg_bytes).decode('utf-8')

            time.sleep(0.033)

    except Exception as e:
        stream_died[0] = True
    finally:
        running[0] = False

    reader_thread.join(timeout=3.0)
    ai_thread.join(timeout=2.0)

    return not stream_died[0]
