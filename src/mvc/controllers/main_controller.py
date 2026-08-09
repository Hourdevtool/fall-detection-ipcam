import asyncio

from ...mvc.models.camera_manager import CameraManager
from ...mvc.models.network_scanner import NetworkScanner
from ...mvc.views.main_view import MainView

class MainController:
    def __init__(self, page):
        self.page = page
        self.camera_manager = CameraManager()
        self.network_scanner = NetworkScanner(self.camera_manager)
        self.view = MainView(page)
        self.system_id = None
        self.is_paired_cached = None
        
        # Connect callbacks
        self.network_scanner.on_camera_found = self.on_camera_found # type: ignore
        self.view.settings_button.on_click = self.on_settings_click
        self.view.show_code_button.on_click = self.on_show_code_click
        
        self.view.register_button.on_click = self.on_register_click
        self.view.intruder_toggle.on_change = self.on_intruder_toggle
        
        self.webcam_running = False
        self.webcam_cap = None
        
        import os
        os.environ["INTRUDER_DETECTION"] = "0"
        
    def start(self):
        from api_server.pairing import get_or_create_system_id
        self.system_id = get_or_create_system_id()
        self.check_pairing_status()
        self.network_scanner.start_scanning()
        self.start_frame_updater()

    def check_pairing_status(self):
        from api_server.pairing import get_current_pair_code
        from api_server.database import is_system_paired
        
        if not self.system_id:
            return
            
        paired = is_system_paired(self.system_id)
        if paired != self.is_paired_cached:
            self.is_paired_cached = paired
            if paired:
                self.view.hide_pairing_code()
                self.view.show_code_button.visible = True
            else:
                pair_info = get_current_pair_code(self.system_id)
                if pair_info:
                    self.view.show_pairing_code(pair_info["code"])
                self.view.show_code_button.visible = False
            self.view.page.update()

    def on_show_code_click(self, e):
        from api_server.pairing import get_current_pair_code
        pair_info = get_current_pair_code(self.system_id)
        if pair_info:
            self.view.show_pairing_code(pair_info["code"])
            # Hide the icon button since the banner is now visible
            self.view.show_code_button.visible = False
            self.view.page.update()

    def on_camera_found(self, ip, rtsp_url, needs_naming, temp_path, serial_number):
        if needs_naming:
            if not self.camera_manager.mark_pending(ip, serial_number):
                print(f"ℹ️ [IP: {ip}] มี Dialog ตั้งชื่อกล้องตัวนี้เปิดอยู่อยู่แล้ว ข้ามการเปิดซ้ำ")
                return

            def save_callback(ip_addr, name):
                self.camera_manager.save_camera_name(serial_number, ip_addr, name)
                # เริ่มสตรีมหลังจากตั้งชื่อเสร็จ
                self.camera_manager.start_stream(ip_addr, rtsp_url, serial_number)
                self.camera_manager.clear_pending(ip_addr, serial_number)

            def cancel_callback(ip_addr):
                self.camera_manager.clear_pending(ip_addr, serial_number)
                
            self.view.show_naming_dialog(ip, temp_path, save_callback, cancel_callback)
        else:
            # Update IP in config if necessary, and load the name
            name = self.camera_manager.load_camera_name(serial_number, ip)
            # เริ่มสตรีมทันทีถ้าเคยตั้งชื่อแล้ว
            self.camera_manager.start_stream(ip, rtsp_url, serial_number)

    def start_frame_updater(self):
        async def updater_loop():
            """อัพเดตเฟรมบน Flet event loop โดยตรง — แก้ปัญหาภาพไม่อัพเดตจนกว่าจะขยับ UI"""
            loop_count = 0
            last_b64_dict = {}  # 🚀 เก็บ b64 ล่าสุดเพื่อ skip เฟรมซ้ำ
            while True:
                try:
                    # 🚀 ตรวจสอบสถานะการเชื่อมต่อทุกๆ ~10 วินาที (200 รอบ x 50ms)
                    if loop_count % 200 == 0:
                        self.check_pairing_status()
                    loop_count += 1
                    
                    # 🚀 get_frames() ตอนนี้ return base64 ที่ pre-encode แล้ว
                    # ไม่ต้องทำ base64.b64encode ใน UI thread อีกต่อไป!
                    b64_dict = self.camera_manager.get_frames()
                    
                    # 🚀 Skip ถ้าเฟรมไม่เปลี่ยน (ลด overhead ของ page.update)
                    has_new_frame = False
                    for ip, b64 in b64_dict.items():
                        if b64 and last_b64_dict.get(ip) is not b64:
                            has_new_frame = True
                            break
                    
                    if has_new_frame or loop_count % 20 == 0:
                        # มีเฟรมใหม่ หรือ ทุก ~1 วินาที force update (เพื่ออัพเดต overlay status)
                        active_cams = dict(self.camera_manager.active_cameras)
                        cam_names = dict(self.camera_manager.camera_names)
                        self.view.update_grid(b64_dict, active_cams, cam_names)
                        last_b64_dict = b64_dict

                    # 🚀 เพิ่มเป็น 20 FPS (เดิม 10 FPS) — ลื่นขึ้นเยอะ
                    await asyncio.sleep(0.05)
                except Exception as e:
                    err_str = str(e).lower()
                    if "destroyed" in err_str or "session" in err_str:
                        break
                    print(f"Error in updater loop: {e}")
                    await asyncio.sleep(0.5)

        # run_task() รันบน Flet event loop → page.update() จะ push ไปที่ client ทันที
        self.page.run_task(updater_loop)

    def on_settings_click(self, e):
        def save_callback(username, password, line_bot_token, line_group_id):
            self.network_scanner.save_credentials(username, password, line_bot_token, line_group_id)

        self.view.show_settings_dialog(
            self.network_scanner.user,
            self.network_scanner.password,
            self.network_scanner.line_bot_token,
            self.network_scanner.line_group_id,
            save_callback
        )

    def on_intruder_toggle(self, e):
        import os
        is_on = self.view.intruder_toggle.value
        os.environ["INTRUDER_DETECTION"] = "1" if is_on else "0"
        print(f"Intruder Detection is now {'ON' if is_on else 'OFF'}")

    def on_register_click(self, e):
        self.view.show_registration_dialog(
            self.start_webcam,
            self.capture_face,
            self.stop_webcam
        )

    def start_webcam(self, image_control):
        import cv2
        import base64
        self.webcam_running = True
        self.webcam_cap = cv2.VideoCapture(0)
        
        async def update_webcam():
            while self.webcam_running and self.webcam_cap and self.webcam_cap.isOpened():
                ret, frame = await asyncio.to_thread(self.webcam_cap.read)
                if ret and self.webcam_running:
                    # Save frame for capture
                    self.current_webcam_frame = frame
                    _, buffer = await asyncio.to_thread(
                        cv2.imencode, '.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                    )
                    b64_str = base64.b64encode(buffer).decode('utf-8')
                    if image_control.src != f"data:image/jpeg;base64,{b64_str}":
                        image_control.src = f"data:image/jpeg;base64,{b64_str}"
                        image_control.update()
                await asyncio.sleep(0.033)
                
        self.page.run_task(update_webcam)

    def capture_face(self, name, angle, status_text_control):
        if not hasattr(self, 'current_webcam_frame') or self.current_webcam_frame is None:
            status_text_control.value = "ไม่พบภาพจากกล้อง"
            status_text_control.color = "red"
            status_text_control.update()
            return
            
        import cv2
        import os
        import threading
        from src.services.face_recognition_service import FaceRecognitionService
        
        status_text_control.value = f"กำลังประมวลผลและดึงลักษณะใบหน้า {angle} (อาจใช้เวลาสักครู่)..."
        status_text_control.color = "amber"
        status_text_control.update()
        
        # Save temp image
        temp_img_path = f"temp_capture_{angle}.jpg"
        cv2.imwrite(temp_img_path, self.current_webcam_frame)
        
        def process():
            try:
                service = FaceRecognitionService()
                success, msg = service.register_face(temp_img_path, name, angle)
                if success:
                    status_text_control.value = f"บันทึกภาพ {angle} ของ {name} สำเร็จ!"
                    status_text_control.color = "green"
                else:
                    status_text_control.value = f"เกิดข้อผิดพลาด: {msg}"
                    status_text_control.color = "red"
            except Exception as e:
                status_text_control.value = f"Error: {e}"
                status_text_control.color = "red"
                
            if os.path.exists(temp_img_path):
                try:
                    os.remove(temp_img_path)
                except:
                    pass
                
            status_text_control.update()
            
        threading.Thread(target=process, daemon=True).start()

    def stop_webcam(self):
        self.webcam_running = False
        if self.webcam_cap:
            self.webcam_cap.release()
            self.webcam_cap = None
