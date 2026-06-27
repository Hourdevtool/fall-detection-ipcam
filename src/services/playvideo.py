import av
import cv2
import base64
import numpy as np
import json
import os
import threading
import time
from detection import FallDetector

def play_stream_pyav(ip, rtsp_url, active_cameras, frame_buffer, camera_names):
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

    detector = FallDetector(on_fall_callback=_on_fall)

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

    # --- Processing loop: ประมวลผล AI ทุก N เฟรม, encode JPEG+base64 ในนี้เลย ---
    frame_count = 0
    ai_interval = 3  # ประมวลผล AI ทุก 3 เฟรม (ลดภาระ CPU/GPU)
    jpeg_params = [cv2.IMWRITE_JPEG_QUALITY, 70]  # ลด quality เล็กน้อยเพื่อความเร็ว

    try:
        while running[0] and active_cameras.get(ip, False):
            # ตรวจสอบว่าสตรีมค้างหรือไม่ (ไม่ได้เฟรมใหม่เกิน 8 วินาที)
            if time.time() - last_frame_time[0] > 8.0:
                print(f"⚠️ [Processor] IP: {ip} -> ไม่ได้รับเฟรมใหม่เกิน 8 วินาที (สตรีมค้าง) ทำการปิดเพื่อเชื่อมต่อใหม่")
                running[0] = False
                break

            frame_img = latest_frame[0]
            if frame_img is not None:
                # รีเซ็ตเฟรมล่าสุดเพื่อไม่ให้ประมวลผลซ้ำจนกว่าจะมีเฟรมใหม่
                latest_frame[0] = None
                
                cam_name = camera_names.get(ip, camera_name)

                # Resize เฟรม
                img_resized = cv2.resize(frame_img, (640, 360))

                frame_count += 1
                if frame_count % ai_interval == 0:
                    # เฟรมนี้ทำ AI เต็ม (YOLO + Fall Detection)
                    processed_frame = detector.process_frame(img_resized, cam_name)
                else:
                    # เฟรมนี้แค่วาด overlay สถานะล่าสุด (เร็วมาก)
                    processed_frame = detector.draw_overlay(img_resized, cam_name)

                # Encode JPEG + base64 ตรงนี้เลย (ไม่ต้องส่ง numpy array ข้าม process)
                _, buffer = cv2.imencode('.jpg', processed_frame, jpeg_params)
                b64_str = base64.b64encode(buffer).decode('utf-8')
                frame_buffer[ip] = b64_str

            time.sleep(0.016)  # ~60 FPS cap
    except Exception as e:
        print(f"❌ [Processor] IP: {ip} -> {type(e).__name__}: {e}")
    finally:
        running[0] = False
        active_cameras[ip] = False
        if ip in frame_buffer:
            del frame_buffer[ip]
        container.close()
        print(f"🛑 [ปิดสตรีม] IP: {ip}")
