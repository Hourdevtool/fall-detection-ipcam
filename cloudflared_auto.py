import subprocess
import re
import requests
import time
import sys
import threading
import os
import json
from dotenv import load_dotenv
import requests
import time
import sys
import threading
import os
from dotenv import load_dotenv

# โหลดค่าจากไฟล์ .env
load_dotenv()

# ==========================================
# ⚙️ การตั้งค่า Firebase (กรุณาแก้ไขให้ตรงกับโปรเจกต์ของคุณ)
# ==========================================
# นำมาจาก Firebase Console -> Project Settings -> Service accounts -> Database secrets หรือใช้ URL ตรงๆ
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "https://YOUR-FIREBASE-PROJECT-ID.firebaseio.com")

# ชื่อตัวแปร (Node) หลักใน Database
DATABASE_NODE_PREFIX = "/systems"

# พอร์ตของ API Server ที่รันอยู่ (ใน main.py รันที่พอร์ต 8000)
LOCAL_PORT = int(os.getenv("LOCAL_PORT", "8000"))

# ==========================================

def update_firebase(url):
    """ฟังก์ชันสำหรับอัปเดต URL ไปยัง Firebase Realtime Database แบบแยกตามอุปกรณ์"""
    try:
        # 1. อ่านไฟล์ system_config.json เพื่อดึง pair_code และ system_id
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "system_config.json")
        system_id = "unknown"
        pair_code = "unknown"
        
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                system_id = config.get("system_id", "unknown")
                pair_code = config.get("pair_code", "unknown")
                
        if system_id == "unknown":
            print("❌ [ERROR] ไม่พบ system_id ใน system_config.json กรุณารันระบบหลักเพื่อสร้างรหัสก่อน")
            return

        # 2. ตั้ง URL ปลายทางไปที่โฟลเดอร์ systems/{system_id}
        firebase_url = f"{FIREBASE_DATABASE_URL}{DATABASE_NODE_PREFIX}/{system_id}.json"
        
        data = {
            "url": url, 
            "updated_at": time.time(),
            "status": "online"
        }
        
        # ส่ง HTTP PUT ไปยัง Firebase Realtime Database (อัปเดตหรือสร้างใหม่)
        # ใช้ PATCH เพื่อไม่ให้ทับข้อมูลอื่นใน node นี้
        response = requests.patch(firebase_url, json=data)
        
        if response.status_code == 200:
            print(f"✅ [SUCCESS] อัปเดต URL ประจำกล้อง (System: {system_id}) ไปที่ Firebase สำเร็จ: {url}")
        else:
            print(f"❌ [ERROR] ไม่สามารถอัปเดต Firebase ได้. Status Code: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"❌ [ERROR] เกิดข้อผิดพลาดในการเชื่อมต่อ Firebase: {e}")

def run_cloudflared():
    """ฟังก์ชันสำหรับรัน cloudflared และดักจับ URL"""
    print(f"🚀 กำลังเริ่มต้น Cloudflare Tunnel สำหรับพอร์ต {LOCAL_PORT}...")
    
    # รันคำสั่ง cloudflared (ต้องติดตั้งโปรแกรม cloudflared ในเครื่อง Mini PC ก่อน)
    # ใช้ 'cloudflared.exe' แทนเผื่อรันบน Windows แล้วหาไม่เจอ
    command = ["cloudflared.exe", "tunnel", "--url", f"http://localhost:{LOCAL_PORT}"]
    
    # cloudflared จะพ่น log ออกมาทาง stderr
    process = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
    
    # Regex สำหรับค้นหา URL แบบสุ่มของ TryCloudflare
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    
    current_url = None

    try:
        # เช็คให้แน่ใจว่า process.stderr มีอยู่จริง (ช่วยแก้ปัญหาแจ้งเตือน Type None is not iterable)
        if process.stderr is not None:
            # อ่าน Log แบบ Real-time
            for line in process.stderr:
                # print(line, end="") # ปลดคอมเมนต์บรรทัดนี้ถ้าอยากดู Log ทั้งหมดของ Cloudflare
                
                # ค้นหา URL ในบรรทัดนั้น
                match = url_pattern.search(line)
                
                if match:
                    found_url = match.group(0)
                    # ถ้าเจอ URL ใหม่ที่ไม่ซ้ำกับของเดิม ให้อัปเดต
                    if found_url != current_url:
                        current_url = found_url
                        print(f"\n🌐 [CLOUDFLARE] ได้รับ URL ใหม่: {current_url}")
                        
                        # บันทึก URL ลงไฟล์สำหรับให้ service อื่นในเครื่องเอาไปใช้ (เช่น ส่ง LINE)
                        try:
                            cf_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "cloudflare_url.txt")
                            with open(cf_file, "w", encoding="utf-8") as f:
                                f.write(current_url)
                        except Exception as e:
                            print(f"⚠️ ไม่สามารถบันทึกไฟล์ cloudflare_url.txt ได้: {e}")
                        
                        # อัปเดตขึ้น Firebase (ทำใน Background Thread จะได้ไม่บล็อกการอ่าน Log)
                        threading.Thread(target=update_firebase, args=(current_url,)).start()

    except KeyboardInterrupt:
        print("\n🛑 หยุดการทำงานของ Cloudflare Tunnel")
        process.terminate()
        sys.exit(0)

if __name__ == "__main__":
    # ตรวจสอบว่าติดตั้ง requests หรือยัง
    try:
        import requests
    except ImportError:
        print("❌ ไม่พบไลบรารี requests. กรุณารันคำสั่ง: pip install requests")
        sys.exit(1)
        
    if "YOUR-FIREBASE-PROJECT-ID" in FIREBASE_DATABASE_URL:
        print("⚠️ คำเตือน: คุณยังไม่ได้แก้ไข FIREBASE_DATABASE_URL ในสคริปต์")
        print("กรุณาเปิดไฟล์ cloudflared_auto.py แล้วใส่ URL ของ Firebase โปรเจกต์คุณก่อน\n")
        
    run_cloudflared()
