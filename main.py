import flet as ft
import threading
import uvicorn
import os

from src.mvc.controllers.main_controller import MainController

from api_server.server import app, set_camera_manager

def run_api_server():
    # แก้ปัญหาภาษา/Encoding บน Windows
    os.environ["PYTHONIOENCODING"] = "utf-8"
    print("🚀 Starting API Server in background thread...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

_global_camera_manager = None
_global_network_scanner = None

def main(page: ft.Page):
    global _global_camera_manager, _global_network_scanner
    
    # ตั้งค่าหน้าจอเป็นแบบเต็มหน้าจอ (Fullscreen) และไม่มีกรอบขอบหน้าต่าง (Frameless/Borderless)
    page.window.full_screen = True
    page.window.frameless = True
    page.window.title_bar_hidden = True
    
    controller = MainController(page)
    
    # กรณีที่มีการหลุดการเชื่อมต่อและ reconnect ใหม่ (session ใหม่)
    if _global_camera_manager is not None:
        print("🔄 Flet reconnected. Restoring CameraManager and NetworkScanner state...")
        controller.camera_manager = _global_camera_manager
        controller.network_scanner = _global_network_scanner
        # ผูก callback ใหม่เข้ากับ controller ตัวใหม่
        controller.network_scanner.on_camera_found = controller.on_camera_found
        
        from api_server.pairing import get_or_create_system_id
        controller.system_id = get_or_create_system_id()
        controller.check_pairing_status()
        controller.start_frame_updater()
    else:
        _global_camera_manager = controller.camera_manager
        _global_network_scanner = controller.network_scanner
        # แชร์ CameraManager instance ให้กับ API Server เพื่อให้ Web App ดึงภาพได้
        set_camera_manager(controller.camera_manager)
        controller.start()

if __name__ == "__main__":
    import multiprocessing
    # Required for Windows multiprocessing
    multiprocessing.freeze_support()
    
    # รัน API Server ใน background thread
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    
    # รัน Cloudflare Tunnel ใน background thread อีกเส้น (ดึงมาจากไฟล์ cloudflared_auto.py)
    try:
        from cloudflared_auto import run_cloudflared
        cloudflare_thread = threading.Thread(target=run_cloudflared, daemon=True)
        cloudflare_thread.start()
    except ImportError:
        print("⚠️ ไม่สามารถโหลด cloudflared_auto ได้ โปรดตรวจสอบว่ามีไฟล์นี้อยู่")
    
    # รัน Flet App เป็นแบบ Windows Native App (ไม่ใช่บนเว็บเบราว์เซอร์)
    ft.app(target=main, view=ft.AppView.FLET_APP)

