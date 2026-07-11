import cv2
import os
from detection import FallDetector

def main():
    print("==============================================")
    print("🎥 Fall Guard - Webcam Full System Test 🎥")
    print("==============================================")
    
    # เปิดโหมดตรวจจับผู้บุกรุก
    os.environ["INTRUDER_DETECTION"] = "1"
    
    # โหลด AI (จะโหลดทั้ง YOLO และ Face Recognition)
    print("⚙️ กำลังโหลดโมเดล AI (การล้ม + ตรวจจับใบหน้า)... อาจใช้เวลาสักครู่")
    detector = FallDetector(conf_threshold=0.4)
    
    print("🎬 กำลังเปิดกล้อง Webcam...")
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("❌ ไม่สามารถเปิดกล้อง Webcam ได้")
        return
        
    print("✅ ระบบพร้อมทำงาน! (กดปุ่ม 'q' ที่หน้าต่างภาพเพื่อออก)")
    
    frame_count = 0
    ai_interval = 3  # ทำ AI ทุก 3 เฟรม
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ ไม่สามารถอ่านภาพจากกล้องได้")
            break
        
        # 🚀 Resize ภาพจากกล้องให้เล็กลงก่อน (ลดภาระ)
        frame = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_LINEAR)
        
        frame_count += 1
        if frame_count % ai_interval == 0:
            # ประมวลผล AI เต็ม (YOLO จะ resize เพิ่มเองภายใน)
            processed_frame = detector.process_frame(frame, camera_name="Webcam Test")
        else:
            # วาดแค่ overlay (เร็วมาก)
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
