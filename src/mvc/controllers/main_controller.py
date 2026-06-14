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

    def on_camera_found(self, ip, rtsp_url, needs_naming, temp_path):
        if needs_naming:
            def save_callback(ip, name):
                self.camera_manager.save_camera_name(ip, name)
                # เริ่มสตรีมหลังจากตั้งชื่อเสร็จ
                self.camera_manager.start_stream(ip, rtsp_url)
                
            self.view.show_naming_dialog(ip, temp_path, save_callback)
        else:
            # เริ่มสตรีมทันทีถ้าเคยตั้งชื่อแล้ว
            self.camera_manager.start_stream(ip, rtsp_url)

    def start_frame_updater(self):
        async def updater_loop():
            """อัพเดตเฟรมบน Flet event loop โดยตรง — แก้ปัญหาภาพไม่อัพเดตจนกว่าจะขยับ UI"""
            loop_count = 0
            while True:
                try:
                    # ตรวจสอบสถานะการเชื่อมต่อทุกๆ ~3 วินาที (90 รอบ x 33ms)
                    if loop_count % 90 == 0:
                        self.check_pairing_status()
                    loop_count += 1
                    
                    # frame_buffer เก็บ base64 string โดยตรง
                    b64_dict = self.camera_manager.get_frames()
                    
                    if b64_dict:
                        self.view.update_grid(b64_dict)

                    await asyncio.sleep(0.033)  # ~30 FPS UI update
                except Exception as e:
                    err_str = str(e).lower()
                    if "destroyed" in err_str or "session" in err_str:
                        break
                    print(f"Error in updater loop: {e}")
                    await asyncio.sleep(0.5)

        # run_task() รันบน Flet event loop → page.update() จะ push ไปที่ client ทันที
        self.page.run_task(updater_loop)

    def on_settings_click(self, e):
        def save_callback(username, password):
            self.network_scanner.save_credentials(username, password)

        self.view.show_settings_dialog(
            self.network_scanner.user,
            self.network_scanner.password,
            save_callback
        )
