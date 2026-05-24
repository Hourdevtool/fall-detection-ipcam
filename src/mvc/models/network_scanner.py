import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from onvif import ONVIFCamera

COMMON_PORTS = [
    5000, 8080, 8899, 80, 81, 202, 554, 8000, 9000, 9001,
    9002, 9003, 9004, 9005, 9006, 9007, 9008, 9009,
]

class NetworkScanner:
    def __init__(self, camera_manager):
        self.camera_manager = camera_manager
        # on_camera_found signature: on_camera_found(ip, rtsp_url, needs_naming, temp_img_path)
        self.on_camera_found = None
        self.user = "admin"
        self.password = "ctnphrae1234"

    def get_local_subnet(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return ".".join(local_ip.split(".")[:-1])

    def check_port(self, ip, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0

    def get_onvif(self, ip):
        # Skip if already active
        if self.camera_manager.active_cameras.get(ip, False):
            return

        print(f"🔍 [IP: {ip}] เริ่มสแกน...")
        for port in COMMON_PORTS:
            if not self.check_port(ip, port):
                continue
            
            print(f"✅ [IP: {ip}] พอร์ต {port} เปิดอยู่ กำลังเชื่อมต่อ ONVIF...")
            try:
                cam = ONVIFCamera(ip, port, self.user, self.password)
                media_service = cam.create_media_service()
                token = media_service.GetProfiles()[0].token # type: ignore

                request = media_service.create_type("GetStreamUri")
                request.ProfileToken = token
                request.StreamSetup = {
                    "Stream": "RTP-Unicast",
                    "Transport": {"Protocol": "RTSP"},
                }
                rtsp_url = media_service.GetStreamUri(request).Uri # type: ignore

                if "://" in rtsp_url and f"{self.user}:" not in rtsp_url:
                    parts = rtsp_url.split("://")
                    rtsp_url = f"{parts[0]}://{self.user}:{self.password}@{parts[1]}"
                
                print(f"📷 [IP: {ip}] พบกล้อง ONVIF (RTSP: {rtsp_url})")

                # Check if camera needs naming
                import json
                import os
                needs_naming = True
                if os.path.exists("cameras.json"):
                    try:
                        with open("cameras.json", "r", encoding="utf-8") as f:
                            config = json.load(f)
                            if ip in config:
                                needs_naming = False
                    except Exception:
                        pass

                temp_path = None
                if needs_naming:
                    import av
                    import cv2
                    import tempfile
                    print(f"📸 [IP: {ip}] กำลังดึงภาพตัวอย่างจากสตรีม...")

                    # ลอง 3 วิธีตามลำดับ: plain → TCP → UDP พร้อม Timeout 5 วินาที
                    av_options_list = [
                        {'stimeout': '5000000'},  # plain พร้อม timeout
                        {'rtsp_transport': 'tcp', 'stimeout': '5000000'},
                        {'rtsp_transport': 'udp', 'stimeout': '5000000'},
                    ]
                    for av_opts in av_options_list:
                        try:
                            container = av.open(rtsp_url, mode='r', options=av_opts or None)
                            for frame in container.decode(video=0):
                                img = frame.to_ndarray(format='bgr24')
                                fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                                import os
                                os.close(fd)
                                cv2.imwrite(temp_path, img)
                                proto = av_opts.get('rtsp_transport', 'plain').upper()
                                print(f"✅ [IP: {ip}] ดึงภาพตัวอย่างสำเร็จ ({proto}): {temp_path}")
                                break
                            container.close()
                            if temp_path:
                                break  # สำเร็จแล้ว หยุด
                        except Exception as e:
                            proto = av_opts.get('rtsp_transport', 'plain').upper()
                            print(f"⚠️ [IP: {ip}] ดึงภาพไม่สำเร็จ ({proto}): {type(e).__name__}: {e}")

                    if not temp_path:
                        print(f"ℹ️ [IP: {ip}] เพิ่มกล้องโดยไม่มีภาพตัวอย่าง")

                if self.on_camera_found:
                    self.on_camera_found(ip, rtsp_url, needs_naming, temp_path)
                return  # Done with this IP

            except Exception as e:
                err_msg = str(e).split('\n')[0][:120]
                print(f"❌ [IP: {ip}] พอร์ต {port}: {type(e).__name__}: {err_msg}")
                continue

    def scan_loop(self):
        subnet = self.get_local_subnet()
        print(f"📡 เริ่มเดินเครื่องสแกนวง LAN: {subnet}.1 ถึง {subnet}.254")
        while True:
            with ThreadPoolExecutor(max_workers=50) as executor:
                for i in range(1, 255):
                    ip = f"{subnet}.{i}"
                    executor.submit(self.get_onvif, ip)
            import time
            time.sleep(15)

    def start_scanning(self):
        threading.Thread(target=self.scan_loop, daemon=True).start()
