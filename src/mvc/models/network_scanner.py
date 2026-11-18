import socket
import threading
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from onvif import ONVIFCamera
from zeep.transports import Transport

PRIMARY_PORTS = [554, 8899, 8000, 8080, 5000, 80]
SECONDARY_PORTS = [81, 202, 9000, 9001, 9002, 9003, 9004, 9005, 9006, 9007, 9008, 9009]
COMMON_PORTS = PRIMARY_PORTS + SECONDARY_PORTS

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
    """ดึง subnet จากทุก network interface ที่มี IPv4 address (เรียง primary route ขึ้นก่อน)
    
    รองรับกรณี PC เชื่อมทั้ง WiFi hotspot (172.20.10.x) และ LAN (192.168.x.x) พร้อมกัน
    """
    subnets = []
    seen = set()

    # 1. Primary outbound interface first (fastest route to LAN/router)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("1.1.1.1", 80))
        local_ip = s.getsockname()[0]
        s.close()
        if local_ip and not local_ip.startswith(("127.", "169.254.")):
            sub = ".".join(local_ip.split(".")[:3])
            seen.add(sub)
            subnets.append(sub)
    except Exception:
        pass

    # 2. All other active non-loopback / non-APIPA interfaces
    try:
        hostname = socket.gethostname()
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for info in addr_infos:
            ip = info[4][0]
            if ip.startswith(("127.", "169.254.")):
                continue
            subnet = ".".join(ip.split(".")[:3])
            if subnet not in seen:
                seen.add(subnet)
                subnets.append(subnet)
    except Exception as e:
        print(f"⚠️ getaddrinfo failed: {e}")

    return subnets


def _get_arp_ips():
    """Read live LAN IPs from OS ARP table in <20ms so known hosts are found immediately."""
    ips = []
    try:
        import subprocess
        import re
        output = subprocess.check_output(
            ["arp", "-a"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        for m in re.finditer(r'\b(\d{1,3}(?:\.\d{1,3}){3})\b', output):
            ip = m.group(1)
            if ip.startswith(("127.", "169.254.", "224.", "239.", "255.")) or ip.endswith(".255") or ip.endswith(".0"):
                continue
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def _check_port(ip, port, timeout=0.25):
    """ตรวจสอบว่า port เปิดอยู่หรือไม่"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0
    except Exception:
        return False


def _check_ip_ports(ip, ports=None, timeout=0.25):
    """ตรวจสอบว่า IP นี้มี port ใดเปิดอยู่บ้าง → return (ip, port) หรือ None"""
    for port in (ports or PRIMARY_PORTS):
        if _check_port(ip, port, timeout=timeout):
            return (ip, port)
    return None


def _scanner_process_loop(result_queue: multiprocessing.Queue, stop_event: multiprocessing.Event):
    """ฟังก์ชันหลักของ scanner process — สแกนเร็วแบบ 2 เฟส (ARP + Primary Ports → Secondary Ports)"""
    import time

    print("🔄 [Scanner Process] เริ่มทำงานบน core แยก (multiprocessing)")
    scan_round = 0

    while not stop_event.is_set():
        try:
            subnets = get_all_subnets()
            arp_ips = _get_arp_ips()
            print(f"📡 [Scanner Process] สแกน {len(subnets)} subnet(s): {subnets} (ARP hosts: {len(arp_ips)})")

            found_ips = set()

            # Phase 0: Check live ARP hosts first across PRIMARY_PORTS (<0.5s!)
            if arp_ips:
                with ThreadPoolExecutor(max_workers=min(32, len(arp_ips))) as executor:
                    futures = {executor.submit(_check_ip_ports, ip, PRIMARY_PORTS, 0.25): ip for ip in arp_ips}
                    for future in futures:
                        if stop_event.is_set():
                            break
                        try:
                            result = future.result(timeout=5)
                            if result:
                                ip, port = result
                                found_ips.add(ip)
                                result_queue.put(("found", ip, port))
                        except Exception:
                            pass

            # Build full subnet IP list (excluding already-found ARP IPs)
            all_ips = []
            for subnet in subnets:
                for i in range(1, 255):
                    cand = f"{subnet}.{i}"
                    if cand not in found_ips:
                        all_ips.append(cand)

            # Phase 1: Fast scan on PRIMARY_PORTS across all subnet IPs
            with ThreadPoolExecutor(max_workers=64) as executor:
                futures = {executor.submit(_check_ip_ports, ip, PRIMARY_PORTS, 0.25): ip for ip in all_ips}
                for future in futures:
                    if stop_event.is_set():
                        break
                    try:
                        result = future.result(timeout=6)
                        if result:
                            ip, port = result
                            found_ips.add(ip)
                            result_queue.put(("found", ip, port))
                    except Exception:
                        pass

            # Phase 2: Secondary ports only on initial scan or every 4th cycle to avoid flooding Wi-Fi/hotspot
            remaining_ips = [ip for ip in all_ips if ip not in found_ips]
            if remaining_ips and (scan_round % 4 == 0) and not stop_event.is_set():
                with ThreadPoolExecutor(max_workers=64) as executor:
                    futures = {executor.submit(_check_ip_ports, ip, SECONDARY_PORTS, 0.18): ip for ip in remaining_ips}
                    for future in futures:
                        if stop_event.is_set():
                            break
                        try:
                            result = future.result(timeout=8)
                            if result:
                                ip, port = result
                                found_ips.add(ip)
                                result_queue.put(("found", ip, port))
                        except Exception:
                            pass

            scan_round += 1
            # ส่งสัญญาณว่ารอบสแกนเสร็จแล้ว
            result_queue.put(("scan_complete", None, None))

        except Exception as e:
            print(f"❌ [Scanner Process] Error: {e}")

        # รอ 15 วินาทีก่อนสแกนรอบถัดไป (ลดภาระ Wi-Fi/Hotspot ไม่ให้รบกวนสตรีม RTSP)
        for _ in range(150):  # 150 x 0.1s = 15s
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
        self._probing_ips = set()
        self._probe_lock = threading.Lock()

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

    def check_port(self, ip, port, timeout=0.35):
        return _check_port(ip, port, timeout=timeout)

    def _needs_naming(self, serial_number, ip):
        import json
        import os
        if os.path.exists("config/cameras.json"):
            try:
                with open("config/cameras.json", "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if serial_number in config or ip in config:
                        return False
            except Exception:
                pass
        return True

    def _capture_preview_image(self, ip, rtsp_url):
        import av
        import cv2
        import os
        import tempfile
        print(f"📸 [IP: {ip}] กำลังดึงภาพตัวอย่างจากสตรีม...")

        av_options_list = [
            {"timeout": "2000000", "probesize": "262144", "analyzeduration": "500000"},
            {"rtsp_transport": "tcp", "timeout": "2000000", "probesize": "262144", "analyzeduration": "500000"},
            {"rtsp_transport": "udp", "timeout": "2000000", "probesize": "262144", "analyzeduration": "500000"},
        ]
        candidates = [
            rtsp_url,
            f"rtsp://{self.user}:{self.password}@{ip}:554/onvif1",
            f"rtsp://{self.user}:{self.password}@{ip}:554/onvif2",
            f"rtsp://{ip}:554/onvif1",
            f"rtsp://{self.user}:{self.password}@{ip}:554/user={self.user}&password={self.password}&channel=1&stream=1.sdp",
            f"rtsp://{self.user}:{self.password}@{ip}:554/user={self.user}&password={self.password}&channel=1&stream=0.sdp",
            f"rtsp://{self.user}:{self.password}@{ip}:554/live/ch0",
        ]
        seen = set()
        for candidate in [u for u in candidates if u and u not in seen and not seen.add(u)]:
            for av_opts in av_options_list:
                try:
                    container = av.open(candidate, mode='r', options=av_opts, timeout=2.5)
                    if not container.streams.video:
                        container.close()
                        continue
                    stream = container.streams.video[0]
                    stream.thread_type = 'SLICE'
                    for packet in container.demux(stream):
                        if packet.dts is None:
                            continue
                        try:
                            for frame in packet.decode():
                                img = frame.to_ndarray(format='bgr24')
                                fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                                os.close(fd)
                                cv2.imwrite(temp_path, img)
                                proto = av_opts.get('rtsp_transport', 'auto').upper()
                                print(f"✅ [IP: {ip}] ดึงภาพตัวอย่างสำเร็จ ({proto}): {temp_path}")
                                container.close()
                                return temp_path
                        except Exception:
                            pass
                    container.close()
                except Exception:
                    pass
        print(f"ℹ️ [IP: {ip}] เพิ่มกล้องโดยไม่มีภาพตัวอย่าง")
        return None

    def get_onvif(self, ip, port=None):
        """เชื่อมต่อ ONVIF กับกล้องที่ IP นี้ — รันบน main process"""
        # Skip if already active or pending naming dialog
        if self.camera_manager.is_pending_or_active(ip):
            return

        with self._probe_lock:
            if ip in self._probing_ips:
                return
            self._probing_ips.add(ip)

        try:
            # Skip local machine IP (e.g. FastAPI on 8000)
            try:
                local_ips = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
                if ip in local_ips or ip.startswith("127."):
                    return
            except Exception:
                pass

            # Fast path: if this IP is a cached known camera and RTSP port 554 is open, connect immediately!
            for cached in self.camera_manager.get_cached_cameras():
                c_ip = cached.get("ip")
                c_url = cached.get("rtsp_url")
                c_sn = cached.get("serial_number")
                if c_ip == ip and c_url and c_sn and not self._needs_naming(c_sn, ip):
                    if self.check_port(ip, 554, timeout=0.35):
                        print(f"⚡ [IP: {ip}] พบกล้องที่เคยเชื่อมต่อแล้ว — เชื่อมต่อด่วนผ่าน Cache ({c_url})")
                        if self.on_camera_found:
                            self.on_camera_found(ip, c_url, False, None, c_sn)
                        return

            print(f"🔍 [IP: {ip}] เริ่มเชื่อมต่อ ONVIF...")

            # ถ้ามี port ที่รู้แล้ว ลองที่นั้นก่อน แล้วค่อยลองพอร์ตอื่น
            ports_to_try = []
            if port and port != 554:
                ports_to_try.append(port)
            ports_to_try.extend([p for p in COMMON_PORTS if p != port and p != 554])

            for try_port in ports_to_try:
                if not self.check_port(ip, try_port, timeout=0.3):
                    continue

                print(f"✅ [IP: {ip}] พอร์ต {try_port} เปิดอยู่ กำลังเชื่อมต่อ ONVIF...")
                try:
                    transport = Transport(timeout=3, operation_timeout=4)
                    cam = ONVIFCamera(ip, try_port, self.user, self.password, transport=transport)
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

                    needs_naming = self._needs_naming(serial_number, ip)
                    temp_path = self._capture_preview_image(ip, rtsp_url) if needs_naming else None

                    if self.on_camera_found:
                        self.on_camera_found(ip, rtsp_url, needs_naming, temp_path, serial_number)
                    return

                except Exception as e:
                    err_msg = str(e).split('\n')[0][:120]
                    print(f"❌ [IP: {ip}] พอร์ต {try_port}: {type(e).__name__}: {err_msg}")
                    continue

            # Fallback: ถ้า ONVIF SOAP ล้มเหลวทุกพอร์ต แต่พอร์ต 554 เปิดอยู่ ให้ลองดึง RTSP ตรงๆ
            if self.check_port(ip, 554, timeout=0.4):
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
                        opts = {"timeout": "2000000", "probesize": "262144", "analyzeduration": "500000"}
                        container = av.open(candidate, mode='r', options=opts, timeout=2.5)
                        if container.streams.video:
                            container.close()
                            rtsp_url = candidate
                            serial_number = get_mac_address(ip) or ip
                            needs_naming = self._needs_naming(serial_number, ip)

                            print(f"📷 [IP: {ip}] พบกล้องผ่าน RTSP Direct (URL: {rtsp_url})")
                            if self.on_camera_found:
                                self.on_camera_found(ip, rtsp_url, needs_naming, None, serial_number)
                            return
                        container.close()
                    except Exception:
                        pass
        finally:
            with self._probe_lock:
                self._probing_ips.discard(ip)

    def _probe_cached_cameras(self):
        """Immediately probe known cached cameras on startup (<0.5s) before full scan."""
        cached_list = self.camera_manager.get_cached_cameras()
        # Also include raw IP keys saved in cameras.json (for backwards compat if no cache yet)
        known_ips = {c.get("ip") for c in cached_list if c.get("ip")}
        for key in list(self.camera_manager.camera_names.keys()):
            parts = str(key).split('.')
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                if key not in known_ips:
                    cached_list.append({"ip": key, "rtsp_url": None, "serial_number": key})

        for cam in cached_list:
            if self._stop_event.is_set():
                return
            ip = cam.get("ip")
            if not ip or self.camera_manager.is_pending_or_active(ip):
                continue
            rtsp_url = cam.get("rtsp_url")
            serial_number = cam.get("serial_number") or ip
            if rtsp_url and not self._needs_naming(serial_number, ip) and self.check_port(ip, 554, timeout=0.4):
                print(f"⚡ [Startup Cache] เชื่อมต่อกล้อง {ip} ทันที")
                if self.on_camera_found:
                    self.on_camera_found(ip, rtsp_url, False, None, serial_number)
            elif self.check_port(ip, 554, timeout=0.4) or self.check_port(ip, 80, timeout=0.3):
                threading.Thread(target=self.get_onvif, args=(ip, None), daemon=True).start()

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
        """เริ่มสแกนกล้องแบบ multiprocessing — พร้อมเชื่อมกล้องที่เคยรู้จักทันที"""
        threading.Thread(
            target=self._probe_cached_cameras,
            daemon=True,
            name="CachedCamProbe",
        ).start()

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
