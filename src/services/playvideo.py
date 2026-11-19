import base64
import json
import os
import re
import socket
import threading
import time
from urllib.parse import urlparse

import av
import cv2
import numpy as np
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


# Low-latency PyAV / FFmpeg options (FFmpeg 6+ uses 'timeout' in microseconds, not deprecated 'stimeout')
_LOW_LATENCY_BASE_OPTS = {
    'timeout': '5000000',
    'fflags': 'nobuffer',
    'flags': 'low_delay',
    'probesize': '262144',
    'analyzeduration': '500000',
    'max_delay': '500000',
}

# TCP first for reliable Wi-Fi/hotspot streaming, then AUTO & UDP fallbacks
_AV_OPTIONS_LIST = [
    {**_LOW_LATENCY_BASE_OPTS, 'rtsp_transport': 'tcp'},
    dict(_LOW_LATENCY_BASE_OPTS),
    {**_LOW_LATENCY_BASE_OPTS, 'rtsp_transport': 'udp'},
]

# Cache last known working (url, opts) per camera IP for sub-second reconnects
_LAST_WORKING_STREAM = {}
_LAST_WORKING_LOCK = threading.Lock()
_BASE_BACKOFF_SEC = 1
_MAX_BACKOFF_SEC = 5
_STALL_TIMEOUT_SEC = 12.0


def _tcp_reachable(rtsp_url, timeout=0.8):
    """Fail fast in <1s when RTSP host is offline instead of hanging through all URL candidates."""
    if not rtsp_url or not rtsp_url.lower().startswith("rtsp://"):
        return True
    try:
        parsed = urlparse(rtsp_url)
        host = parsed.hostname
        port = parsed.port or 554
        if not host:
            return True
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
    except Exception:
        return True


def _build_candidate_urls(ip, rtsp_url):
    """Order primary/ONVIF RTSP URL first, followed by common fallback paths without duplicates."""
    user = "admin"
    password = ""
    port = "554"
    m = re.match(r'rtsp://([^:]+):([^@]*)@([^:/]+)(?::(\d+))?(.*)', rtsp_url or '')
    if m:
        user = m.group(1)
        password = m.group(2)
        ip = m.group(3)
        port = m.group(4) or "554"

    candidates = [
        rtsp_url,
        f"rtsp://{user}:{password}@{ip}:{port}/onvif1",
        f"rtsp://{user}:{password}@{ip}:{port}/onvif2",
        f"rtsp://{ip}:{port}/onvif1",
        f"rtsp://{user}:{password}@{ip}:{port}/user={user}&password={password}&channel=1&stream=0.sdp",
        f"rtsp://{user}:{password}@{ip}:{port}/user={user}&password={password}&channel=1&stream=1.sdp",
        f"rtsp://{user}:{password}@{ip}:{port}/live/ch0",
    ]
    seen = set()
    return [u for u in candidates if u and u not in seen and not seen.add(u)]


def _open_stream(ip, rtsp_url, active_cameras=None):
    """Try to open RTSP stream quickly — tries cached working profile first and fails fast if offline."""
    if not _tcp_reachable(rtsp_url, timeout=0.8):
        return None, None

    attempts = []
    with _LAST_WORKING_LOCK:
        cached = _LAST_WORKING_STREAM.get(ip)
    if cached:
        attempts.append(cached)

    for candidate in _build_candidate_urls(ip, rtsp_url):
        for opts in _AV_OPTIONS_LIST:
            if cached and candidate == cached[0] and opts == cached[1]:
                continue
            attempts.append((candidate, opts))

    for candidate, opts in attempts:
        if active_cameras is not None and not active_cameras.get(ip, False):
            return None, None
        proto = opts.get('rtsp_transport', 'auto').upper()
        try:
            container = av.open(candidate, 'r', options=dict(opts), timeout=(2.5, _STALL_TIMEOUT_SEC))
            if container.streams.video:
                with _LAST_WORKING_LOCK:
                    _LAST_WORKING_STREAM[ip] = (candidate, opts)
                print(f"✅ [สตรีม] IP: {ip} เชื่อมต่อสำเร็จด้วย {proto} ({candidate})")
                return container, proto
            container.close()
        except Exception:
            if cached and (candidate, opts) == cached:
                with _LAST_WORKING_LOCK:
                    _LAST_WORKING_STREAM.pop(ip, None)

    print(f"❌ [สตรีม] IP: {ip} ไม่สามารถเชื่อมต่อ RTSP ได้")
    return None, None


def play_stream_pyav(ip, rtsp_url, active_cameras, frame_buffer, camera_names, frame_buffer_b64=None, camera_config=None):
    print(f"🎬 [เริ่มดึงภาพ] IP: {ip}")

    if camera_names is None:
        camera_names = {}
        try:
            if os.path.exists("config/cameras.json"):
                with open("config/cameras.json", "r", encoding="utf-8") as f:
                    camera_names = json.load(f)
        except Exception:
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

    # Auto-reconnect indefinitely whenever network/camera drops, until stop_stream sets active_cameras[ip] = False
    while active_cameras.get(ip, False):
        if retry_count > 0:
            backoff = min(_MAX_BACKOFF_SEC, _BASE_BACKOFF_SEC * retry_count)
            print(f"🔄 [Reconnect] IP: {ip} — รอ {backoff}s ก่อนเชื่อมต่อใหม่ (ครั้งที่ {retry_count})...")
            for _ in range(int(backoff * 10)):
                if not active_cameras.get(ip, False):
                    _cleanup(ip, frame_buffer, frame_buffer_b64)
                    return
                time.sleep(0.1)

        container, _proto = _open_stream(ip, rtsp_url, active_cameras=active_cameras)
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
            # Clear cached transport profile if stream stalled so reconnect can try TCP/AUTO fallback
            with _LAST_WORKING_LOCK:
                _LAST_WORKING_STREAM.pop(ip, None)
            # Clear frozen last frame so UI immediately switches to reconnecting state
            _cleanup(ip, frame_buffer, frame_buffer_b64)
            retry_count += 1
        else:
            break

    _cleanup(ip, frame_buffer, frame_buffer_b64)
    active_cameras[ip] = False
    print(f"🛑 [ปิดสตรีม] IP: {ip}")


def _cleanup(ip, frame_buffer, frame_buffer_b64):
    frame_buffer.pop(ip, None)
    if frame_buffer_b64 is not None:
        frame_buffer_b64.pop(ip, None)


def _run_stream_pipeline(ip, container, detector, camera_names, camera_name,
                         active_cameras, frame_buffer, frame_buffer_b64,
                         camera_config=None):
    splitter = FrameSplitter(camera_config)

    latest_av_frame = [None]
    raw_seq = [0]
    ai_seq = [0]
    bgr_cache = [0, None]  # [seq, bgr_ndarray]
    frame_lock = threading.Lock()
    convert_lock = threading.Lock()
    frame_event = threading.Event()
    last_frame_time = [time.time()]
    running = [True]
    stream_died = [False]

    def _get_latest_bgr():
        with frame_lock:
            seq = raw_seq[0]
            av_f = latest_av_frame[0]
        if av_f is None:
            return 0, None
        with convert_lock:
            if bgr_cache[0] == seq and bgr_cache[1] is not None:
                return seq, bgr_cache[1]
            with frame_lock:
                seq = raw_seq[0]
                av_f = latest_av_frame[0]
            if av_f is None:
                return 0, None
            bgr = av_f.to_ndarray(format="bgr24")
            bgr_cache[0] = seq
            bgr_cache[1] = bgr
            return seq, bgr

    # ─── Reader thread: drains RTSP packets immediately without BGR overhead ─
    def read_frames():
        consecutive_errors = 0
        try:
            if not container.streams.video:
                stream_died[0] = True
                return
            stream = container.streams.video[0]
            # SLICE/NONE avoids multi-frame reorder buffering latency inside FFmpeg decoder
            stream.thread_type = "SLICE"
            for packet in container.demux(stream):
                if not running[0] or not active_cameras.get(ip, False):
                    break
                if packet.dts is None and packet.pts is None:
                    continue
                try:
                    for frame in packet.decode():
                        with frame_lock:
                            latest_av_frame[0] = frame
                            raw_seq[0] += 1
                        last_frame_time[0] = time.time()
                        consecutive_errors = 0
                        frame_event.set()
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
            frame_event.set()

    reader_thread = threading.Thread(target=read_frames, daemon=True, name=f"Reader-{ip}")
    reader_thread.start()

    # ─── AI thread: event-driven zero-sleep latest-frame inference ─────────
    def ai_worker():
        last_processed_seq = 0
        while running[0] and active_cameras.get(ip, False):
            frame_event.wait(timeout=0.1)
            frame_event.clear()
            if not running[0] or not active_cameras.get(ip, False):
                break
            seq, frame_img = _get_latest_bgr()
            if frame_img is None or seq == last_processed_seq:
                continue
            last_processed_seq = seq
            cam_name = camera_names.get(ip, camera_name)
            try:
                sub_frames = splitter.split_frame(frame_img)
                if len(sub_frames) > 1:
                    for label, sub_frame in sub_frames:
                        sub_id = f"{ip}_{label}"
                        sub_name = f"{cam_name} ({label})"
                        detector.process_frame(sub_frame, sub_name, camera_id=sub_id, draw=False)
                else:
                    _, sub_frame = sub_frames[0]
                    detector.process_frame(sub_frame, cam_name, camera_id=ip, draw=False)
                ai_seq[0] += 1
            except Exception:
                pass

    ai_thread = threading.Thread(target=ai_worker, daemon=True, name=f"AI-{ip}")
    ai_thread.start()

    # ─── Display loop (up to 30 FPS, 960x540 crisp overlay) ─────────────────
    DISPLAY_W = 960
    DISPLAY_H = 540
    last_disp_raw = 0
    last_disp_ai = 0
    last_encode_time = 0.0

    try:
        while running[0] and active_cameras.get(ip, False):
            now = time.time()

            if now - last_frame_time[0] > _STALL_TIMEOUT_SEC:
                print(f"⚠️ [สตรีม {ip}] ไม่มีภาพเกิน {_STALL_TIMEOUT_SEC:.0f}s — กำลังเชื่อมต่อใหม่...")
                stream_died[0] = True
                running[0] = False
                break

            seq, raw = _get_latest_bgr()
            cur_ai = ai_seq[0]
            if raw is not None and (seq != last_disp_raw or cur_ai != last_disp_ai or now - last_encode_time > 0.25):
                last_disp_raw = seq
                last_disp_ai = cur_ai
                last_encode_time = now
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

                jpeg_bytes = _encode_jpeg(display_frame, quality=75)
                frame_buffer[ip] = jpeg_bytes

                if frame_buffer_b64 is not None:
                    frame_buffer_b64[ip] = base64.b64encode(jpeg_bytes).decode('utf-8')

            time.sleep(0.033)

    except Exception:
        stream_died[0] = True
    finally:
        running[0] = False
        frame_event.set()

    reader_thread.join(timeout=3.0)
    ai_thread.join(timeout=2.0)

    return not stream_died[0]
