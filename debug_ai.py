import cv2
import sys
import os
import time
import json
from detection import FallDetector

def main():
    print("==============================================")
    print("🛡️ Fall Guard - AI Detection Debugger 🛡️")
    print("==============================================")
    
    # 1. ตรวจสอบไฟล์โมเดล
    yolo_path = os.path.join("Tools", "yolov8n-pose.pt")
    rf_path = os.path.join("Tools", "fall_detect_model.pkl")
    
    if not os.path.exists(yolo_path):
        print(f"❌ ไม่พบโมเดล YOLO ที่ตำแหน่ง: '{yolo_path}'")
        return
    if not os.path.exists(rf_path):
        print(f"❌ ไม่พบโมเดล Random Forest ที่ตำแหน่ง: '{rf_path}'")
        return
        
    print(f"✅ พบไฟล์โมเดลเรียบร้อย")
    
    # 2. เลือกแหล่งที่มาของวิดีโอ
    print("\nกรุณาเลือกแหล่งที่มาของสตรีม/วิดีโอ:")
    print("1) กล้องเว็บแคม (Webcam 0)")
    print("2) เลือกกล้อง IP จาก config/cameras.json")
    print("3) ระบุ RTSP URL ด้วยตัวเอง")
    choice = input("เลือกข้อ (1-3, กด Enter เลือกข้อ 1): ").strip()
    
    source = 0
    if choice == '2':
        if os.path.exists("config/cameras.json"):
            with open("config/cameras.json", "r", encoding="utf-8") as f:
                cams = json.load(f)
            if cams:
                print("\nกล้องที่พบในระบบ:")
                cam_list = list(cams.items())
                for i, (ip, name) in enumerate(cam_list):
                    print(f"{i+1}) {name} ({ip})")
                cam_choice = input(f"เลือกกล้องลำดับที่ (1-{len(cam_list)}): ").strip()
                try:
                    ip = cam_list[int(cam_choice)-1][0]
                    user = "admin"
                    password = "ctnphrae1234"
                    if os.path.exists("config/config.json"):
                        with open("config/config.json", "r") as f:
                            cfg = json.load(f)
                            user = cfg.get("username", "admin")
                            password = cfg.get("password", "ctnphrae1234")
                    source = f"rtsp://{user}:{password}@{ip}:554/onvif1"
                    print(f"🔗 สตรีมที่เลือก: {source}")
                except Exception as e:
                    print(f"❌ เลือกไม่ถูกต้อง จะใช้งานกล้องเว็บแคมแทน. Error: {e}")
                    source = 0
            else:
                print("⚠️ ไฟล์ config/cameras.json ว่างเปล่า จะใช้งานกล้องเว็บแคมแทน")
        else:
            print("⚠️ ไม่พบไฟล์ config/cameras.json จะใช้งานกล้องเว็บแคมแทน")
    elif choice == '3':
        source = input("ระบุ RTSP URL: ").strip()
        
    # 3. กำหนดค่า YOLO Confidence Threshold
    conf_input = input("\nกำหนดค่าความมั่นใจขั้นต่ำของ YOLO (0.1 - 1.0, ค่าเริ่มต้นของระบบคือ 0.7, แนะนำลอง 0.4): ").strip()
    try:
        conf_threshold = float(conf_input) if conf_input else 0.4
    except ValueError:
        conf_threshold = 0.4
        
    print(f"\n⚙️ กำลังโหลดตัวตรวจจับ FallDetector ด้วยค่า CONF_THRESHOLD = {conf_threshold}...")
    detector = FallDetector(conf_threshold=conf_threshold)
    
    print("\n🎬 กำลังเชื่อมต่อแหล่งข้อมูล...")
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"❌ ไม่สามารถเปิดกล้อง/สตรีมได้: {source}")
        return
        
    print(f"\n🚀 เริ่มการดีบั๊กตัว AI สำเร็จ!")
    print("💡 หน้าต่างแสดงผลจะเปิดขึ้น กดปุ่ม 'q' บนหน้าต่างนั้นเพื่อออกจากโปรแกรม\n")
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ ไม่สามารถดึงเฟรมภาพได้ หรือสตรีมสิ้นสุดลง")
            break
            
        frame_resized = cv2.resize(frame, (640, 360))
        
        # รัน YOLO ตรวจหาบุคคลแยกต่างหากเพื่อนำรายละเอียดมาปริ้นดีบั๊ก
        results = detector.pose_model(frame_resized, verbose=False, conf=detector.conf_threshold)
        
        persons_found = 0
        if results[0].boxes is not None:
            persons_found = len(results[0].boxes)
            
        print(f"\r[เฟรมที่ {frame_count:04d}] ตรวจพบคน: {persons_found} คน", end="", flush=True)
        
        if persons_found > 0:
            print(f"\n--- ข้อมูลดีบั๊กในเฟรมที่ {frame_count} ---")
            for idx, box in enumerate(results[0].boxes):
                box_conf = float(box.conf[0].cpu().item())
                print(f"👤 คนที่ #{idx}: ความมั่นใจของ YOLO (Pose Confidence) = {box_conf:.2f}")
                
            # ตรวจสอบการหาโครงกระดูก (Keypoints)
            if results[0].keypoints is not None and len(results[0].keypoints) > 0:
                kpts = results[0].keypoints.xyn[0].cpu().numpy()
                row = kpts.flatten().tolist()
                
                if detector.fall_model:
                    prediction = detector.fall_model.predict([row])[0]
                    prob = detector.fall_model.predict_proba([row])[0]
                    rf_conf = prob[prediction]
                    
                    xywh = results[0].boxes.xywh[0].cpu().numpy()
                    w, h = xywh[2], xywh[3]
                    aspect_ratio = w / h if h > 0 else 0
                    
                    print(f"   📐 อัตราส่วนความกว้างต่อความสูงของกล่อง (Aspect Ratio): {aspect_ratio:.2f}")
                    print(f"   🧠 ผลวิเคราะห์ท่าทางจาก Random Forest: ทำนายผล = {prediction} (1=ล้ม, 0=ปกติ), ความมั่นใจ = {rf_conf:.2f}")
            else:
                print("   ⚠️ ตรวจพบคนแต่ความมั่นใจโครงกระดูกต่ำเกินไป หรือเห็นอวัยวะไม่ครบ ทำให้ประมวลผลต่อไม่ได้")
                
        # ประมวลผลและวาดผลลัพธ์ผ่านหน้าจอดีเทกเตอร์ปกติ
        processed_frame = detector.process_frame(frame_resized)
        cv2.imshow("Fall Guard - AI Debugger", processed_frame)
        
        frame_count += 1
        
        key = cv2.waitKey(20) & 0xFF
        if key == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()
    print("\n🏁 ปิดการดีบั๊กเรียบร้อย.")

if __name__ == "__main__":
    main()
