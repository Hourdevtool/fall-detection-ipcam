import cv2
import os
from detection import FallDetector

def main():
    print("==============================================")
    print("🎥 Fall Guard - Webcam Full System Test 🎥")
    print("==============================================")
    
    # ปิดโหมดตรวจจับใบหน้าชั่วคราว เพื่อลดอาการหน่วง (Lag) ตอนทดสอบท่าทาง
    os.environ["INTRUDER_DETECTION"] = "0"
    
    # โหลด AI (จะโหลดทั้ง YOLO และ Face Recognition)
    print("⚙️ กำลังโหลดโมเดล AI (การล้ม + ตรวจจับใบหน้า)... อาจใช้เวลาสักครู่")
    
    import threading

    def _on_fall(cam_name, frame, timestamp):
        # ปิดการส่ง LINE ชั่วคราวตามที่ผู้ใช้ร้องขอ
        print(f"⚠️ [MOCKED] ตรวจพบการล้มที่ {cam_name}! (ปิดระบบแจ้งเตือน LINE แล้ว)")

    def _on_intruder(cam_name, frame, timestamp):
        # ปิดการส่ง LINE ชั่วคราวตามที่ผู้ใช้ร้องขอ
        print(f"⚠️ [MOCKED] ตรวจพบผู้บุกรุกที่ {cam_name}! (ปิดระบบแจ้งเตือน LINE แล้ว)")

    detector = FallDetector(conf_threshold=0.4, on_fall_callback=_on_fall, on_intruder_callback=_on_intruder)
    
    print("🎬 กำลังเปิดกล้อง Webcam...")
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("❌ ไม่สามารถเปิดกล้อง Webcam ได้")
        return
        
    print("✅ ระบบพร้อมทำงาน! (กดปุ่ม 'q' ที่หน้าต่างภาพเพื่อออก)")
    
    frame_count = 0
    ai_interval = 1  # ทำ AI ทุกเฟรม เพื่อไม่ให้เส้น Skeleton กะพริบ
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ ไม่สามารถอ่านภาพจากกล้องได้")
            break
        
        # 🚀 Resize ภาพจากกล้องให้เล็กลงก่อน (ลดภาระ)
        frame = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_LINEAR)
        
        frame_count += 1
        if frame_count % ai_interval == 0:
            # ประมวลผล AI เต็ม
            processed_frame = detector.process_frame(frame, camera_name="Webcam Test")
        else:
            # วาดแค่ overlay (กรณีที่ตั้ง ai_interval > 1)
            processed_frame = detector.draw_overlay(frame, camera_name="Webcam Test")
        
        # แสดงผลภาพ
        cv2.imshow("Webcam Full System Test", processed_frame)
        
        # กด 'q' เพื่อออก
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()
    print("🛑 ปิดระบบทดสอบเรียบร้อย")

if __name__ == "__main__":
    main()
