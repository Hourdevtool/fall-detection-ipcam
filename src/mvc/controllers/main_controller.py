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
        
        # Connect callbacks
        self.network_scanner.on_camera_found = self.on_camera_found # type: ignore
        
    def start(self):
        self.network_scanner.start_scanning()
        self.start_frame_updater()

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
            while True:
                try:
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
