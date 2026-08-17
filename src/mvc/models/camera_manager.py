import json
import os
import threading
from src.services.playvideo import play_stream_pyav

class CameraManager:
    def __init__(self):
        # ใช้ dict ธรรมดา + threading แทน multiprocessing.Manager().dict()
        # → ไม่ต้อง pickle/unpickle frame ทุกรอบ (ประหยัดเวลาหลาย 100ms)
        self.active_cameras = {}
        self.frame_buffer = {}       # เก็บ raw JPEG bytes สำหรับ MJPEG web stream
        self.frame_buffer_b64 = {}   # 🚀 เก็บ base64 string ที่ pre-encode แล้ว สำหรับ Flet UI
        self.camera_names = {}
        self.camera_configs = {}     # 📷 Per-camera config (dual camera, split mode, etc.)
        self.pending_naming = set()
        self._lock = threading.Lock()
        self.config_file = "config/cameras.json"
        self._load_names()

    def is_pending_or_active(self, ip, serial_number=None):
        with self._lock:
            if self.active_cameras.get(ip, False):
                return True
            if ip in self.pending_naming:
                return True
            if serial_number and serial_number in self.pending_naming:
                return True
            return False

    def mark_pending(self, ip, serial_number=None):
        with self._lock:
            if self.active_cameras.get(ip, False) or ip in self.pending_naming or (serial_number and serial_number in self.pending_naming):
                return False
            self.pending_naming.add(ip)
            if serial_number:
                self.pending_naming.add(serial_number)
            return True

    def clear_pending(self, ip, serial_number=None):
        with self._lock:
            self.pending_naming.discard(ip)
            if serial_number:
                self.pending_naming.discard(serial_number)

    def _load_names(self):
        """Load camera names and configs from cameras.json.
        
        Supports two formats:
          Old: {"ip": "name"}
          New: {"ip": {"name": "xxx", "dual": true, "split": "vertical"}}
        """
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    for key, value in config.items():
                        if isinstance(value, str):
                            # Old format: {"ip": "name"}
                            self.camera_names[key] = value
                            self.camera_configs[key] = {"name": value}
                        elif isinstance(value, dict):
                            # New format: {"ip": {"name": "xxx", "dual": true, ...}}
                            self.camera_names[key] = value.get("name", key)
                            self.camera_configs[key] = value
                        else:
                            self.camera_names[key] = str(value)
            except Exception:
                pass

    def load_camera_name(self, serial_number, ip):
        # ลองหาด้วย serial number ก่อน
        if serial_number in self.camera_names:
            # ถ้า IP เปลี่ยนไป ให้อัพเดตในหน่วยความจำ
            self.camera_names[ip] = self.camera_names[serial_number]
            return self.camera_names[serial_number]
        # ถ้าไม่มี ลองหาด้วย IP (เผื่อของเก่า)
        return self.camera_names.get(ip, ip)

    def save_camera_name(self, serial_number, ip, name):
        self.camera_names[serial_number] = name
        self.camera_names[ip] = name # เก็บไว้ทั้งคู่ใน runtime ให้เข้าถึงด้วย IP ได้ตอน render ภาพ
        config = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass
                
        config[serial_number] = name
        # ลบ IP เก่าออกจาก config เพื่อให้สะอาด (ถ้ามี)
        if ip in config and serial_number != ip:
            del config[ip]
            
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def start_stream(self, ip, rtsp_url, serial_number=None):
        if self.active_cameras.get(ip, False):
            return

        self.active_cameras[ip] = True
        # ใช้ threading.Thread แทน multiprocessing.Process
        # → แชร์ dict เดียวกันได้โดยตรง ไม่ต้องผ่าน Manager proxy
        # 🚀 ส่ง frame_buffer_b64 เพิ่มเพื่อให้ camera thread pre-encode base64
        # 📷 ส่ง camera_config สำหรับ dual camera (FNK-D14Z etc.)
        camera_config = self.camera_configs.get(ip) or self.camera_configs.get(serial_number)
        t = threading.Thread(
            target=play_stream_pyav,
            args=(ip, rtsp_url, self.active_cameras, self.frame_buffer, self.camera_names, self.frame_buffer_b64),
            kwargs={'camera_config': camera_config},
            daemon=True,
        )
        t.start()

    def get_frames(self):
        """Return pre-encoded base64 frames สำหรับ Flet UI (ไม่ต้อง encode เองใน UI thread)"""
        return dict(self.frame_buffer_b64)

    def get_raw_frames(self):
        """Return raw JPEG bytes สำหรับ MJPEG web stream"""
        return dict(self.frame_buffer)
