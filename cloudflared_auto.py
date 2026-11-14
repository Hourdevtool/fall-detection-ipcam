import subprocess
import re
import requests
import time
import sys
import threading
import os
import json
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
    """ฟังก์ชันสำหรับอัปเดต URL ไปยัง Firebase Realtime Database แบบแยกตามอุปกรณ์ (พร้อม retry)"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "system_config.json")
    system_id = "unknown"

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                system_id = config.get("system_id", "unknown")
        except Exception:
            pass

    if system_id == "unknown":
        print("❌ [ERROR] ไม่พบ system_id ใน system_config.json กรุณารันระบบหลักเพื่อสร้างรหัสก่อน")
        return

    firebase_url = f"{FIREBASE_DATABASE_URL}{DATABASE_NODE_PREFIX}/{system_id}.json"

    for attempt in range(1, 6):
        try:
            data = {
                "url": url,
                "updated_at": time.time(),
                "status": "online"
            }
            response = requests.patch(firebase_url, json=data, timeout=10)
            if response.status_code == 200:
                print(f"✅ [SUCCESS] อัปเดต URL ประจำกล้อง (System: {system_id}) ไปที่ Firebase สำเร็จ: {url}")
                return
            print(f"❌ [ERROR] ไม่สามารถอัปเดต Firebase ได้ (attempt {attempt}/5). Status Code: {response.status_code}")
        except Exception as e:
            print(f"❌ [ERROR] เชื่อมต่อ Firebase ไม่สำเร็จ (attempt {attempt}/5): {e}")

        time.sleep(min(10, 2 * attempt))

def run_cloudflared():
    """ฟังก์ชันสำหรับรัน cloudflared และดักจับ URL (รีสตาร์ทอัตโนมัติเมื่อเน็ตหลุด)"""
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    current_url = None
    backoff = 2

    while True:
        print(f"🚀 กำลังเริ่มต้น Cloudflare Tunnel สำหรับพอร์ต {LOCAL_PORT}...")
        command = ["cloudflared.exe", "tunnel", "--url", f"http://localhost:{LOCAL_PORT}"]
        process = None

        try:
            process = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, universal_newlines=True)
            if process.stderr is not None:
                for line in process.stderr:
                    match = url_pattern.search(line)
                    if match:
                        found_url = match.group(0)
                        backoff = 2  # Reset backoff once tunnel obtains a URL
                        if found_url != current_url:
                            current_url = found_url
                            print(f"\n🌐 [CLOUDFLARE] ได้รับ URL ใหม่: {current_url}")

                            try:
                                cf_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "cloudflare_url.txt")
                                with open(cf_file, "w", encoding="utf-8") as f:
                                    f.write(current_url)
                            except Exception as e:
                                print(f"⚠️ ไม่สามารถบันทึกไฟล์ cloudflare_url.txt ได้: {e}")

                            threading.Thread(target=update_firebase, args=(current_url,), daemon=True).start()

            ret = process.wait()
            print(f"⚠️ [CLOUDFLARE] Tunnel หยุดทำงาน (code={ret}) — กำลังเชื่อมต่อใหม่ใน {backoff}s...")
        except KeyboardInterrupt:
            print("\n🛑 หยุดการทำงานของ Cloudflare Tunnel")
            if process is not None:
                process.terminate()
            sys.exit(0)
        except Exception as e:
            print(f"⚠️ [CLOUDFLARE] เกิดข้อผิดพลาด: {e} — กำลังเชื่อมต่อใหม่ใน {backoff}s...")
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass

        time.sleep(backoff)
        backoff = min(15, backoff + 2)

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
