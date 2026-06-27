import os
import sys
from datetime import datetime

# เพิ่ม path เพื่อให้สามารถ import จาก api_server ได้
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from api_server.fall_logger import send_line_alert

def main():
    print("[TEST] Sending LINE Messaging API alert using line-bot-sdk...")
    
    # เวลาปัจจุบัน
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    camera_name = "Test Camera (กล้องทดสอบ)"
    
    print(f"From: {camera_name}")
    print(f"Time: {now_str}")
    
    # เรียกใช้ฟังก์ชันส่ง LINE
    send_line_alert(camera_name, now_str)
    
    print("[SUCCESS] Command executed. Please check your LINE group.")

if __name__ == "__main__":
    main()
