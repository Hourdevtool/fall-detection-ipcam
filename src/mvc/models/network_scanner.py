import socket
import threading
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from onvif import ONVIFCamera

COMMON_PORTS = [
    5000, 8080, 8899, 80, 81, 202, 554, 8000, 9000, 9001,
    9002, 9003, 9004, 9005, 9006, 9007, 9008, 9009,
]

def get_mac_address(ip):
    """ดึง MAC Address ของอุปกรณ์ในวง LAN ผ่าน Windows SendARP API หรือ arp -a"""
    try:
        import ctypes
        import socket
        import struct
        ip_bytes = socket.inet_aton(ip)
        dest_ip = struct.unpack('I', ip_bytes)[0]
        mac_addr = (ctypes.c_byte * 6)()
        mac_len = ctypes.c_ulong(6)
        res = ctypes.windll.iphlpapi.SendARP(dest_ip, 0, ctypes.byref(mac_addr), ctypes.byref(mac_len))
        if res == 0:
            return '-'.join(f'{b & 0xff:02X}' for b in mac_addr)
    except Exception:
        pass
        
    try:
        import subprocess
        import re
        output = subprocess.check_output(f"arp -a {ip}", shell=True, text=True)
        match = re.search(r'([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})', output)
        if match:
            return match.group(1).upper().replace(':', '-')
    except Exception:
        pass

    return None

def is_valid_serial(sn):
    if not sn:
        return False
    sn_str = str(sn).strip().lower()
    bogus_values = {"0000000", "00000000", "000000000000", "00:00:00:00:00:00", "1234567890", "unknown", "none", "null"}
    if sn_str in bogus_values or set(sn_str).issubset({'0', ':', '-'}):
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  Scanner Process — ทำงานบน core แยก (multiprocessing)
#  หน้าที่: สแกน port ทุก IP ในทุก subnet → ส่ง IP ที่พบ port เปิดกลับทาง Queue
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_subnets():
    """ดึง subnet จากทุก network interface ที่มี IPv4 address
    
    ใช้ socket.getaddrinfo() กับ hostname เพื่อดึง IP ทุก interface
    รองรับกรณี PC เชื่อมทั้ง WiFi hotspot (172.20.10.x) และ LAN (192.168.x.x) พร้อมกัน
    """
    subnets = set()
    try:
        hostname = socket.gethostname()
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for info in addr_infos:
            ip = info[4][0]
            # ข้าม loopback
            if ip.startswith("127."):
                continue
            subnet = ".".join(ip.split(".")[:3])
            subnets.add(subnet)
    except Exception as e:
        print(f"⚠️ getaddrinfo failed: {e}")

    # Fallback: ถ้าไม่เจอ subnet เลย ใช้วิธีเดิม
    if not subnets:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("1.1.1.1", 80))
            local_ip = s.getsockname()[0]
            s.close()
            subnets.add(".".join(local_ip.split(".")[:3]))
        except Exception:
            pass

    return list(subnets)


def _check_port(ip, port, timeout=0.5):
    """ตรวจสอบว่า port เปิดอยู่หรือไม่"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0
    except Exception:
        return False


def _check_ip_ports(ip):
    """ตรวจสอบว่า IP นี้มี port ใดเปิดอยู่บ้าง → return (ip, port) หรือ None"""
    for port in COMMON_PORTS:
        if _check_port(ip, port):
            return (ip, port)
    return None


def _scanner_process_loop(result_queue: multiprocessing.Queue, stop_event: multiprocessing.Event):
    """ฟังก์ชันหลักของ scanner process — รันบน core แยก วน loop ไม่หยุด
    
    สแกนทุก subnet → ส่ง (ip, port) ที่เจอกลับทาง Queue
    """
    import time

    print("🔄 [Scanner Process] เริ่มทำงานบน core แยก (multiprocessing)")

    while not stop_event.is_set():
        try:
            subnets = get_all_subnets()
            print(f"📡 [Scanner Process] สแกน {len(subnets)} subnet(s): {subnets}")

            # สร้าง list IP ทั้งหมดจากทุก subnet
            all_ips = []
            for subnet in subnets:
                for i in range(1, 255):
                    all_ips.append(f"{subnet}.{i}")

            # ใช้ ThreadPool ภายใน process เพื่อสแกนหลาย IP พร้อมกัน
            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(_check_ip_ports, ip): ip for ip in all_ips}
                for future in futures:
                    if stop_event.is_set():
                        break
                    try:
                        result = future.result(timeout=10)
                        if result:
                            ip, port = result
                            result_queue.put(("found", ip, port))
                    except Exception:
                        pass

            # ส่งสัญญาณว่ารอบสแกนเสร็จแล้ว
            result_queue.put(("scan_complete", None, None))

        except Exception as e:
            print(f"❌ [Scanner Process] Error: {e}")

        # รอ 15 วินาทีก่อนสแกนรอบถัดไป (ลดจาก 30s เพราะสแกนหลาย subnet)
        for _ in range(150):  # 150 x 0.1s = 15s, ตรวจ stop_event ทุก 0.1s
            if stop_event.is_set():
                break
            time.sleep(0.1)

    print("🛑 [Scanner Process] หยุดทำงาน")


class NetworkScanner:
    def __init__(self, camera_manager):
        self.camera_manager = camera_manager
        # on_camera_found signature: on_camera_found(ip, rtsp_url, needs_naming, temp_img_path)
        self.on_camera_found = None
        self.config_file = "config/config.json"
        self.user, self.password, self.line_bot_token, self.line_group_id = self._load_credentials()

        # Multiprocessing resources
        self._result_queue = multiprocessing.Queue()
        self._stop_event = multiprocessing.Event()
        self._scanner_process = None
        self._reader_thread = None

    def _load_credentials(self):
        import json
        import os
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    user = config.get("username", "admin")
                    password = config.get("password", "ctnphrae1234")
                    line_bot_token = config.get("line_bot_token", "")
                    line_group_id = config.get("line_group_id", "")
                    return user, password, line_bot_token, line_group_id
            except Exception:
                pass
        return "admin", "ctnphrae1234", "", ""

    def save_credentials(self, user, password, line_bot_token="", line_group_id=""):
        self.user = user
        self.password = password
        self.line_bot_token = line_bot_token
        self.line_group_id = line_group_id
        import json
        import os
        config = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass
        config["username"] = user
        config["password"] = password
        config["line_bot_token"] = line_bot_token
        config["line_group_id"] = line_group_id
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"❌ Error saving config: {e}")

    def check_port(self, ip, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0

    def get_onvif(self, ip, port=None):
        """เชื่อมต่อ ONVIF กับกล้องที่ IP นี้ — รันบน main process"""
        # Skip if already active or pending naming dialog
        if self.camera_manager.is_pending_or_active(ip):
            return

        # Skip local machine IP (e.g. FastAPI on 8000)
        try:
            local_ips = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
            if ip in local_ips or ip.startswith("127."):
                return
        except Exception:
            pass

        print(f"🔍 [IP: {ip}] เริ่มเชื่อมต่อ ONVIF...")

        # ถ้ามี port ที่รู้แล้ว ลองที่นั้นก่อน แล้วค่อยลองพอร์ตอื่น
        ports_to_try = []
        if port:
            ports_to_try.append(port)
        ports_to_try.extend([p for p in COMMON_PORTS if p != port])

        for try_port in ports_to_try:
            if not self.check_port(ip, try_port):
                continue
            
            print(f"✅ [IP: {ip}] พอร์ต {try_port} เปิดอยู่ กำลังเชื่อมต่อ ONVIF...")
            try:
                cam = ONVIFCamera(ip, try_port, self.user, self.password)
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

                # Get Serial Number or hardware MAC Address
                serial_number = None
                try:
                    devicemgmt = cam.create_devicemgmt_service()
                    device_info = devicemgmt.GetDeviceInformation()
                    if device_info and hasattr(device_info, 'SerialNumber') and device_info.SerialNumber:
                        sn_candidate = str(device_info.SerialNumber).strip()
                        if is_valid_serial(sn_candidate):
                            serial_number = sn_candidate
                except Exception as e:
                    print(f"ℹ️ [IP: {ip}] ดึง SerialNumber จาก ONVIF ไม่ได้: {e}")

                if not serial_number:
                    mac = get_mac_address(ip)
                    if mac:
                        serial_number = mac
                        print(f"📌 [IP: {ip}] ดึง MAC Address สำเร็จ: {mac}")
                    else:
                        serial_number = ip
                        print(f"ℹ️ [IP: {ip}] ไม่สามารถดึง MAC Address ได้ ใช้ IP แทน")

                # Check if camera needs naming
                import json
                import os
                needs_naming = True
                if os.path.exists("config/cameras.json"):
                    try:
                        with open("config/cameras.json", "r", encoding="utf-8") as f:
                            config = json.load(f)
                            if serial_number in config:
                                needs_naming = False
                            elif ip in config:
                                # Backward compatibility: if it was saved by IP before
                                needs_naming = False
                    except Exception:
                        pass

                temp_path = None
                if needs_naming:
                    import av
                    import cv2
                    import tempfile
                    print(f"📸 [IP: {ip}] กำลังดึงภาพตัวอย่างจากสตรีม...")

                    av_options_list = [
                        {'stimeout': '2000000'},                               # Auto (เร็วที่สุด)
                        {'rtsp_transport': 'tcp', 'stimeout': '2000000'},
                        {'rtsp_transport': 'udp', 'stimeout': '2000000'},
                    ]
                    # Candidate URLs
                    candidates = [
                        rtsp_url,
                        f"rtsp://{self.user}:{self.password}@{ip}:554/onvif1",
                        f"rtsp://{self.user}:{self.password}@{ip}:554/onvif2",
                        f"rtsp://{ip}:554/onvif1",
                        f"rtsp://{self.user}:{self.password}@{ip}:554/user={self.user}&password={self.password}&channel=1&stream=1.sdp",
                        f"rtsp://{self.user}:{self.password}@{ip}:554/user={self.user}&password={self.password}&channel=1&stream=0.sdp",
                        f"rtsp://{self.user}:{self.password}@{ip}:554/live/ch0",
                    ]
                    for candidate in candidates:
                        for av_opts in av_options_list:
                            try:
                                container = av.open(candidate, mode='r', options=av_opts or None)
                                if not container.streams.video:
                                    container.close()
                                    continue
                                stream = container.streams.video[0]
                                stream.thread_type = 'AUTO'
                                for packet in container.demux(stream):
                                    if packet.dts is None:
                                        continue
                                    try:
                                        for frame in packet.decode():
                                            img = frame.to_ndarray(format='bgr24')
                                            fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                                            os.close(fd)
                                            cv2.imwrite(temp_path, img)
                                            proto = av_opts.get('rtsp_transport', 'plain').upper()
                                            print(f"✅ [IP: {ip}] ดึงภาพตัวอย่างสำเร็จ ({proto}): {temp_path}")
                                            break
                                    except Exception:
                                        pass
                                    if temp_path:
                                        break
                                container.close()
                                if temp_path:
                                    break
                            except Exception:
                                pass
                        if temp_path:
                            break

                    if not temp_path:
                        print(f"ℹ️ [IP: {ip}] เพิ่มกล้องโดยไม่มีภาพตัวอย่าง")

                if self.on_camera_found:
                    self.on_camera_found(ip, rtsp_url, needs_naming, temp_path, serial_number)
                return  # Done with this IP

            except Exception as e:
                err_msg = str(e).split('\n')[0][:120]
                print(f"❌ [IP: {ip}] พอร์ต {try_port}: {type(e).__name__}: {err_msg}")
                continue

        # Fallback: ถ้า ONVIF SOAP ล้มเหลวทุกพอร์ต แต่พอร์ต 554 เปิดอยู่ ให้ลองดึง RTSP ตรงๆ
        if self.check_port(ip, 554):
            print(f"📡 [IP: {ip}] ลองเชื่อมต่อแบบ RTSP Direct Fallback...")
            rtsp_candidates = [
                f"rtsp://{self.user}:{self.password}@{ip}:554/onvif1",
                f"rtsp://{self.user}:{self.password}@{ip}:554/onvif2",
                f"rtsp://{ip}:554/onvif1",
                f"rtsp://{ip}:554/onvif2",
                f"rtsp://{self.user}:{self.password}@{ip}:554/user={self.user}&password={self.password}&channel=1&stream=0.sdp",
                f"rtsp://{self.user}:{self.password}@{ip}:554/live/ch0",
            ]
            for candidate in rtsp_candidates:
                try:
                    import av
                    container = av.open(candidate, mode='r', options={'stimeout': '2000000'})
                    if container.streams.video:
                        container.close()
                        rtsp_url = candidate
                        mac = get_mac_address(ip) or ip
                        serial_number = mac

                        # Check if camera needs naming
                        import json
                        import os
                        needs_naming = True
                        if os.path.exists("config/cameras.json"):
                            try:
                                with open("config/cameras.json", "r", encoding="utf-8") as f:
                                    config = json.load(f)
                                    if serial_number in config or ip in config:
                                        needs_naming = False
                            except Exception:
                                pass

                        print(f"📷 [IP: {ip}] พบกล้องผ่าน RTSP Direct (URL: {rtsp_url})")
                        if self.on_camera_found:
                            self.on_camera_found(ip, rtsp_url, needs_naming, None, serial_number)
                        return
                except Exception:
                    pass

    def _queue_reader_loop(self):
        """Thread ที่คอยอ่านผลจาก scanner process → เรียก get_onvif() บน main process
        
        ทำงานเป็น daemon thread บน main process
        """
        import queue

        print("📨 [Queue Reader] เริ่มรอรับผลจาก Scanner Process...")

        while not self._stop_event.is_set():
            try:
                msg = self._result_queue.get(timeout=1.0)
                msg_type, ip, port = msg

                if msg_type == "found":
                    # ส่ง ONVIF connection ไปทำบน thread แยก (ใน main process)
                    # เพื่อไม่ให้ block queue reader
                    threading.Thread(
                        target=self.get_onvif,
                        args=(ip, port),
                        daemon=True,
                    ).start()

                elif msg_type == "scan_complete":
                    print("✅ [Queue Reader] สแกนครบ 1 รอบ รอรอบถัดไป...")

            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ [Queue Reader] Error: {e}")

        print("🛑 [Queue Reader] หยุดทำงาน")

    def start_scanning(self):
        """เริ่มสแกนกล้องแบบ multiprocessing — ใช้ 1 core สำหรับ port scanning"""
        # เริ่ม scanner process (1 core แยก)
        self._scanner_process = multiprocessing.Process(
            target=_scanner_process_loop,
            args=(self._result_queue, self._stop_event),
            daemon=True,
            name="CameraScanner",
        )
        self._scanner_process.start()
        print(f"🚀 Scanner Process เริ่มทำงาน (PID: {self._scanner_process.pid})")

        # เริ่ม queue reader thread บน main process
        self._reader_thread = threading.Thread(
            target=self._queue_reader_loop,
            daemon=True,
            name="QueueReader",
        )
        self._reader_thread.start()

    def stop_scanning(self):
        """หยุด scanner process และ queue reader"""
        self._stop_event.set()
        if self._scanner_process and self._scanner_process.is_alive():
            self._scanner_process.join(timeout=5)
            if self._scanner_process.is_alive():
                self._scanner_process.terminate()
        print("🛑 Scanner หยุดทำงานแล้ว")
