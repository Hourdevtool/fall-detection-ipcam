import json
import os
import threading
from src.services.playvideo import play_stream_pyav

class CameraManager:
    def __init__(self):
        # ใช้ dict ธรรมดา + threading แทน multiprocessing.Manager().dict()
        # → ไม่ต้อง pickle/unpickle frame ทุกรอบ (ประหยัดเวลาหลาย 100ms)
        self.active_cameras = {}
        self.frame_buffer = {}   # เก็บ base64 string โดยตรง (ไม่ใช่ numpy array)
        self.camera_names = {}
        self.config_file = "cameras.json"
        self._load_names()

    def _load_names(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    for ip, name in config.items():
                        self.camera_names[ip] = name
            except Exception:
                pass

    def load_camera_name(self, ip):
        return self.camera_names.get(ip, ip)

    def save_camera_name(self, ip, name):
        self.camera_names[ip] = name
        config = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass
                
        config[ip] = name
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def start_stream(self, ip, rtsp_url):
        if self.active_cameras.get(ip, False):
            return

        self.active_cameras[ip] = True
        # ใช้ threading.Thread แทน multiprocessing.Process
        # → แชร์ dict เดียวกันได้โดยตรง ไม่ต้องผ่าน Manager proxy
        t = threading.Thread(
            target=play_stream_pyav,
            args=(ip, rtsp_url, self.active_cameras, self.frame_buffer, self.camera_names),
            daemon=True,
        )
        t.start()

    def get_frames(self):
        # Return a shallow copy to prevent dictionary size change during iteration
        return dict(self.frame_buffer)
