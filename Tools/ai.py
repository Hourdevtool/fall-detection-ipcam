import cv2
import numpy as np
import joblib
from ultralytics import YOLO # type: ignore
import time

YOLO_PATH = "yolov8n-pose.pt"
RF_PATH = "fall_detect_model.pkl"
CONF_THRESHOLD = 0.7 # ความมั่นใจของ YOLO 
FALL_FRAMES_TRIGGER = 10      # (กันลั่น)


pose_model = YOLO(YOLO_PATH)
try:
     fall_model = joblib.load(RF_PATH)
except FileExistsError:
    print(f"❌ หาไฟล์ {RF_PATH} ไม่เจอ! เอาไฟล์โมเดลมาวางไว้ที่เดียวกันก่อนนะครับ")
    exit()

cap = cv2.VideoCapture(0)  
if not cap.isOpened():
    print("❌ ไม่สามารถเปิดกล้องได้")
    exit()

fall_counter = 0
status = 'normal'
color = (0,255,0)

while True:
    ret,frame = cap.read()
    if not ret:
        print("Video จบแล้ว - เล่นใหม่")
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        continue


    results = pose_model(frame, verbose  = False , conf= CONF_THRESHOLD)

    if results[0].keypoints is not None and len(results[0].keypoints) > 0:
         #วาดกระดูก
         frame = results[0].plot()
        
        # ดึงพิกัด keypoints
         kpts = results[0].keypoints.xyn[0].cpu().numpy()
         row = kpts.flatten().tolist()

        #  ทำนาย
         prediction = fall_model.predict([row])[0]
         prob = fall_model.predict_proba([row])[0]
         print(prediction, prob)
         ai_confidence = prob[prediction]
        # match logic
          
         box = results[0].boxes.xywh[0].cpu().numpy()
         w, h = box[2],box[3]
         aspect_ratio = w / h
         is_falling = False
        # logic ตรวจสอบ
         if aspect_ratio < 0.90:
            is_falling = False
            debug_txt = f"Geo: Force Normal (Standing {aspect_ratio:.2f})"

         else:
            # ตอนนี้ตัวเริ่มเอียง หรือนอนแล้ว ให้ AI ดูท่าทางกระดูก
            if prediction == 1: 
                if ai_confidence > 0.6: 
                    is_falling = True
                    debug_txt = f"AI: Fall ({ai_confidence*100:.0f}%)"
                else: 
                    if aspect_ratio > 1.5:
                        is_falling = True
                        debug_txt = "Geo: Fall (AI Low Conf)"
                    else:
                        is_falling = False
                        debug_txt = "AI: Unsure -> Normal"
            
            else: 
                if aspect_ratio > 2.0:
                    is_falling = True 
                    debug_txt = "Geo: Force Fall (Flat)"
                else:
                    is_falling = False
                    debug_txt = f"AI: Normal ({ai_confidence*100:.0f}%)"

       
         if is_falling:  # fall
                fall_counter += 1
         else:
                fall_counter = 0

         if fall_counter >= FALL_FRAMES_TRIGGER:
            status = '!!! FALL DETECTED !!!'
            color = (0, 0, 255) # แดง
         else:
             status = 'normal'
             color = (0, 255, 0) # เขียว
        
         cv2.putText(frame, f"Status: {status}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)
         

         cv2.putText(frame, f"Logic: {debug_txt}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

         cv2.putText(frame, f"Count: {fall_counter}/{FALL_FRAMES_TRIGGER}", (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    else:
        status = "No Person"
        cv2.putText(frame, status, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)

    cv2.imshow('Video Test', frame)  

    if cv2.waitKey(20) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

