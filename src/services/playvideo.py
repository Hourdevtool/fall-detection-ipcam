import av
import cv2
import base64
import numpy as np
import json
import os
import threading
import time
from detection import FallDetector

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


def play_stream_pyav(ip, rtsp_url, active_cameras, frame_buffer, camera_names, frame_buffer_b64=None):
    print(f"🎬 [เริ่มดึงภาพ] IP: {ip} (ด้วย PyAV)")
    
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

    container = None
    av_options_list = [
        {'stimeout': '5000000'},  # plain / auto
        {'rtsp_transport': 'tcp', 'stimeout': '5000000'},
        {'rtsp_transport': 'udp', 'stimeout': '5000000'},
    ]

    for opts in av_options_list:
        proto = opts.get('rtsp_transport', 'auto').upper()
        try:
            test_container = av.open(rtsp_url, 'r', options=opts)
            # ลอง decode 1 เฟรมเพื่อตรวจสอบว่าสตรีมใช้ได้จริง
            test_frame = None
            for f in test_container.decode(video=0):
                test_frame = f
                break
            if test_frame is not None:
                container = test_container
                print(f"✅ [สตรีม] IP: {ip} เชื่อมต่อสำเร็จด้วย {proto}")
                break
            else:
                test_container.close()
                print(f"⚠️ [สตรีม] IP: {ip} ลอง {proto}: เปิดได้แต่ไม่มีเฟรม")
        except Exception as e:
            print(f"⚠️ [สตรีม] IP: {ip} ลอง {proto} ไม่สำเร็จ: {type(e).__name__}: {e}")

    if not container:
        print(f"❌ [สตรีม] IP: {ip} ไม่สามารถเชื่อมต่อสตรีมได้")
        active_cameras[ip] = False
        return

    # --- Reader thread: อ่านเฟรมจาก RTSP อย่างต่อเนื่อง เก็บแค่เฟรมล่าสุด ---
    latest_frame = [None]
    last_frame_time = [time.time()]
    running = [True]

    def read_frames():
        try:
            for frame in container.decode(video=0): # type: ignore
                if not running[0] or not active_cameras.get(ip, False):
                    break
                latest_frame[0] = frame.to_ndarray(format="bgr24")
                last_frame_time[0] = time.time()
        except Exception as e:
            print(f"❌ [Reader] IP: {ip} -> {type(e).__name__}: {e}")
        finally:
            running[0] = False

    reader_thread = threading.Thread(target=read_frames, daemon=True)
    reader_thread.start()

    # --- AI thread: ประมวลผล YOLO + RF แยกออกจาก display pipeline ---
    # เก็บผลลัพธ์ AI ล่าสุดไว้ให้ display loop เอาไปวาด overlay
    ai_result_frame = [None]  # เฟรมที่ผ่าน AI แล้ว (มี skeleton + overlay)
    ai_frame_lock = threading.Lock()

    def ai_worker():
        """รัน AI inference แยก thread — ไม่ block display pipeline"""
        ai_interval_sec = 0.15  # ~6-7 FPS สำหรับ AI (เพียงพอสำหรับ fall detection)
        while running[0] and active_cameras.get(ip, False):
            frame_img = latest_frame[0]
            if frame_img is not None:
                cam_name = camera_names.get(ip, camera_name)
                try:
                    # Resize สำหรับ AI (640x360 เพื่อความแม่นยำ)
                    img_for_ai = cv2.resize(frame_img, (640, 360), interpolation=cv2.INTER_LINEAR)
                    processed = detector.process_frame(img_for_ai, cam_name)
                    with ai_frame_lock:
                        ai_result_frame[0] = processed
                except Exception as e:
                    print(f"⚠️ [AI] IP: {ip} -> {type(e).__name__}: {e}")
            time.sleep(ai_interval_sec)

    ai_thread = threading.Thread(target=ai_worker, daemon=True)
    ai_thread.start()

    # --- Display loop: วาด overlay + encode JPEG + base64 ทันที (ไม่รอ AI) ---
    jpeg_params = [cv2.IMWRITE_JPEG_QUALITY, 50]  # 🚀 ลด quality จาก 60 → 50

    try:
        while running[0] and active_cameras.get(ip, False):
            # ตรวจสอบว่าสตรีมค้างหรือไม่ (ไม่ได้เฟรมใหม่เกิน 8 วินาที)
            if time.time() - last_frame_time[0] > 8.0:
                print(f"⚠️ [Display] IP: {ip} -> ไม่ได้รับเฟรมใหม่เกิน 8 วินาที (สตรีมค้าง)")
                running[0] = False
                break

            # ใช้เฟรมจาก AI ถ้ามี (มี skeleton + status overlay ครบ)
            # ถ้า AI ยังไม่พร้อม ก็ใช้เฟรมดิบ + วาด overlay เบาๆ
            display_frame = None
            with ai_frame_lock:
                if ai_result_frame[0] is not None:
                    display_frame = ai_result_frame[0].copy()

            if display_frame is None:
                # AI ยังไม่มีผลลัพธ์ — ใช้เฟรมดิบ + overlay สถานะล่าสุด
                raw = latest_frame[0]
                if raw is not None:
                    cam_name = camera_names.get(ip, camera_name)
                    display_frame = cv2.resize(raw, (640, 360), interpolation=cv2.INTER_LINEAR)
                    display_frame = detector.draw_overlay(display_frame, cam_name)

            if display_frame is not None:
                # Encode JPEG
                _, buffer = cv2.imencode('.jpg', display_frame, jpeg_params)
                jpeg_bytes = buffer.tobytes()

                # เก็บ raw JPEG bytes สำหรับ MJPEG web stream
                frame_buffer[ip] = jpeg_bytes

                # 🚀 Pre-encode base64 สำหรับ Flet UI (ไม่ต้องทำใน UI thread)
                if frame_buffer_b64 is not None:
                    frame_buffer_b64[ip] = base64.b64encode(jpeg_bytes).decode('utf-8')

            # 🚀 ~30 FPS display rate
            time.sleep(0.033)
    except Exception as e:
        print(f"❌ [Display] IP: {ip} -> {type(e).__name__}: {e}")
    finally:
        running[0] = False
        active_cameras[ip] = False
        if ip in frame_buffer:
            del frame_buffer[ip]
        if frame_buffer_b64 is not None and ip in frame_buffer_b64:
            del frame_buffer_b64[ip]
        container.close()
        print(f"🛑 [ปิดสตรีม] IP: {ip}")
