import av
import cv2
import numpy as np

USER = 'admin'
PASS = 'ctnphrae1234'
IP = '192.168.0.121'
rtsp_url = f"rtsp://{USER}:{PASS}@{IP}:554/onvif1"

print(f"🔗 กำลังเปิดสตรีม PyAV แบบปล่อยอิสระ (ไม่มี Buffer Limit): {rtsp_url}")

try:
    # 💡 พระเอกอยู่ตรงนี้: ปล่อยโล่งๆ ไม่ต้องใส่ options บังคับมันแล้ว
    container = av.open(rtsp_url)
    
    print("✅ สำเร็จ! ดึงภาพได้แล้ว (กด 'q' เพื่อปิด)")
    
    for frame in container.decode(video=0):
        img = frame.to_ndarray(format='bgr24')
        display_frame = cv2.resize(img, (640, 720))
        
        # วาดกรอบสีเขียว
        cv2.rectangle(display_frame, (150, 200), (450, 400), (0, 255, 0), 3)
        cv2.putText(display_frame, "Target Detected", (150, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        
        cv2.imshow("PyAV Free Style", display_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except Exception as e:
    print(f"❌ เกิดข้อผิดพลาด: {e}")

finally:
    cv2.destroyAllWindows()