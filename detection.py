import cv2
import numpy as np
import joblib
from ultralytics import YOLO # type: ignore
import time
import threading
import asyncio
import edge_tts
import pygame
import os
import tempfile

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

class FallDetector:
    def __init__(self, yolo_path=None, rf_path=None, conf_threshold=0.7, fall_trigger_frames=10, on_fall_callback=None, on_intruder_callback=None):
        # ใช้ absolute path เพื่อให้ subprocess หาไฟล์เจอเสมอ
        if yolo_path is None:
            yolo_path = os.path.join(_PROJECT_ROOT,"Tools", "yolov8n-pose.pt")
        if rf_path is None:
            rf_path = os.path.join(_PROJECT_ROOT, "Tools", "multipose_model.pkl")

        self.pose_labels = {
            0: "Walk",
            1: "Stand",
            2: "Sit",
            3: "Bend",
            4: "Fall"
        }

        self.yolo_path = yolo_path
        self.rf_path = rf_path
        self.conf_threshold = conf_threshold
        self.fall_trigger_frames = fall_trigger_frames
        
        # Load models
        print(f"Loading YOLO model from {yolo_path}...")
        self.pose_model = YOLO(self.yolo_path)
        
        print(f"Loading Random Forest model from {rf_path}...")
        try:
             self.fall_model = joblib.load(self.rf_path)
        except Exception as e:
             print(f"❌ Could not load RF model from {self.rf_path}. Error: {e}")
             self.fall_model = None

        self.fall_counter = 0
        self.status = 'normal'
        self.color = (0, 255, 0)
        self.on_fall_callback = on_fall_callback
        self.on_intruder_callback = on_intruder_callback
        self._fall_callback_fired = False  # ป้องกันเรียก callback ซ้ำ
        
        # Audio playback initialization
        try:
            pygame.mixer.init()
        except Exception as e:
            print(f"Failed to initialize pygame mixer: {e}")
            
        self.last_alert_time = 0.0
        self.last_intruder_alert_time = 0.0
        self.alert_cooldown = 10  # seconds between alerts
        
        # 🚀 OPTIMIZATION: Lazy load face service — ไม่โหลดจนกว่าจะเปิดโหมดผู้บุกรุก
        self.face_service = None
        self._face_service_loaded = False
        
        # 🚀 OPTIMIZATION: Cache ผลลัพธ์ face recognition
        self.last_face_check_time = 0
        self.last_intruder_msg = ""
        self.last_intruder_color = (255, 255, 255)
        
        # 🚀 OPTIMIZATION: Pre-calculate YOLO input size (320x192 for speed on CPU)
        self._yolo_input_size = 320

    def _get_face_service(self):
        """Lazy load face recognition service — โหลดครั้งแรกที่ต้องใช้เท่านั้น"""
        if not self._face_service_loaded:
            self._face_service_loaded = True
            try:
                from src.services.face_recognition_service import FaceRecognitionService
                self.face_service = FaceRecognitionService()
                print("✅ Face Recognition Service loaded successfully")
            except Exception as e:
                print(f"⚠️ Could not load Face Recognition Service: {e}")
                self.face_service = None
        return self.face_service

    def async_play_alert(self, camera_name):
        current_time = time.time()
        if current_time - self.last_alert_time < self.alert_cooldown:
            return  # Do not alert too often
            
        self.last_alert_time = current_time
        
        def _speak():
            text = f"แจ้งเตือน ตรวจพบการล้มที่ {camera_name}"
            # Create a temporary file for the audio
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_filename = temp_file.name
            temp_file.close()
            
            async def _generate_audio():
                communicate = edge_tts.Communicate(text, "th-TH-PremwadeeNeural")
                await communicate.save(temp_filename)
                
            try:
                asyncio.run(_generate_audio())
                pygame.mixer.music.load(temp_filename)
                pygame.mixer.music.play()
                
                # Wait for playback to finish
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                    
                # Clean up
                pygame.mixer.music.unload()
                try:
                    os.remove(temp_filename)
                except:
                    pass
            except Exception as e:
                print(f"❌ Error playing alert: {e}")
                
        threading.Thread(target=_speak, daemon=True).start()

    def async_play_intruder_alert(self, camera_name):
        current_time = time.time()
        if current_time - self.last_intruder_alert_time < self.alert_cooldown:
            return
            
        self.last_intruder_alert_time = current_time
        
        def _speak():
            text = f"แจ้งเตือน พบผู้บุกรุกที่ {camera_name}"
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_filename = temp_file.name
            temp_file.close()
            
            async def _generate_audio():
                communicate = edge_tts.Communicate(text, "th-TH-PremwadeeNeural")
                await communicate.save(temp_filename)
                
            try:
                asyncio.run(_generate_audio())
                pygame.mixer.music.load(temp_filename)
                pygame.mixer.music.play()
                
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                    
                pygame.mixer.music.unload()
                try:
                    os.remove(temp_filename)
                except:
                    pass
            except Exception as e:
                print(f"❌ Error playing alert: {e}")
                
        threading.Thread(target=_speak, daemon=True).start()

    def process_frame(self, frame, camera_name="Unknown"):
        if self.fall_model is None:
            cv2.putText(frame, "Model Error", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return frame

        # 🚀 เก็บภาพต้นฉบับไว้สำหรับ Face Recognition (ถ้าใช้ภาพที่มีเส้น Skeleton หน้าอาจจะจับไม่ติด)
        original_frame = frame.copy()

        # 🚀 OPTIMIZATION: Resize ภาพให้เล็กลงก่อนเข้า YOLO (320x192 แทน 640x360)
        h, w = frame.shape[:2]
        scale = self._yolo_input_size / max(h, w)
        small_w = int(w * scale)
        small_h = int(h * scale)
        small_frame = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        
        results = self.pose_model(small_frame, verbose=False, conf=self.conf_threshold)

        if results[0].keypoints is not None and len(results[0].keypoints) > 0:
             # Draw skeleton on the small frame then scale back
             annotated_small = results[0].plot()
             frame = cv2.resize(annotated_small, (w, h), interpolation=cv2.INTER_LINEAR)
            
             # Get keypoints (normalized so they work at any resolution)
             kpts = results[0].keypoints.xyn[0].cpu().numpy()
             row = kpts.flatten().tolist()

             # Predict using RF model
             prediction = self.fall_model.predict([row])[0]
             prob = self.fall_model.predict_proba([row])[0]
             ai_confidence = prob[prediction]
             
             pose_name = self.pose_labels.get(prediction, "Unknown")
              
             box = results[0].boxes.xywh[0].cpu().numpy()
             bw, bh = box[2], box[3]
             aspect_ratio = bw / bh if bh > 0 else 0
             is_falling = False
             debug_txt = f"AI: {pose_name} ({ai_confidence*100:.0f}%)"

             # Logic verification
             if prediction == 4: 
                if ai_confidence > 0.4: 
                    is_falling = True
                elif aspect_ratio > 1.2:
                    is_falling = True
                    debug_txt += " + Geo: Fall"
                else:
                    is_falling = False
                    debug_txt += " -> Ignored"
             else:
                 if aspect_ratio > 1.5:
                     is_falling = True
                     debug_txt = f"Geo: Override {pose_name}->Fall ({aspect_ratio:.1f})"
                 else:
                     is_falling = False

             if is_falling:
                 self.fall_counter += 1
             else:
                 self.fall_counter = 0

             if self.fall_counter >= self.fall_trigger_frames:
                self.status = '!!! FALL DETECTED !!!'
                self.color = (0, 0, 255) # Red
                self.async_play_alert(camera_name)
                # Fire fall callback (once per fall event)
                if self.on_fall_callback and not self._fall_callback_fired:
                    self._fall_callback_fired = True
                    try:
                        self.on_fall_callback(camera_name, frame, time.time())
                    except Exception as e:
                        print(f"❌ Fall callback error: {e}")
             else:
                 self.status = 'normal'
                 self.color = (0, 255, 0) # Green
                 self._fall_callback_fired = False  # Reset for next fall
            
             # --- Intruder Detection (throttled) ---
             intruder_mode = os.environ.get("INTRUDER_DETECTION") == "1"
             intruder_status_txt = self.last_intruder_msg
             intruder_color = self.last_intruder_color
             
             if intruder_mode:
                 face_svc = self._get_face_service()
                 if face_svc:
                     current_time = time.time()
                     # 🚀 OPTIMIZATION: สแกนใบหน้าทุก 2 วินาที (ลดภาระ CPU)
                     if current_time - self.last_face_check_time > 2.0:
                         is_intruder, msg = face_svc.detect_intruder(original_frame)
                         self.last_intruder_msg = msg
                         self.last_face_check_time = current_time
                         intruder_status_txt = msg
                         
                         if is_intruder:
                             self.last_intruder_color = (0, 0, 255)
                             intruder_color = (0, 0, 255)
                             self.async_play_intruder_alert(camera_name)
                             if self.on_intruder_callback:
                                 try:
                                     self.on_intruder_callback(camera_name, original_frame, time.time())
                                 except Exception as e:
                                     print(f"❌ Intruder callback error: {e}")
                         elif msg.startswith("Known"):
                             self.last_intruder_color = (0, 255, 0)
                             intruder_color = (0, 255, 0)
                         else:
                             self.last_intruder_color = (255, 255, 255)
                             intruder_color = (255, 255, 255)
            
             cv2.putText(frame, f"Cam: {camera_name}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
             cv2.putText(frame, f"Pose: {pose_name} ({ai_confidence*100:.0f}%)", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 165, 0), 2)
             cv2.putText(frame, f"Status: {self.status}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 1, self.color, 3)
             cv2.putText(frame, f"Logic: {debug_txt}", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
             cv2.putText(frame, f"Count: {self.fall_counter}/{self.fall_trigger_frames}", (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
             
             if intruder_mode:
                 cv2.putText(frame, f"Face: {intruder_status_txt}", (20, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, intruder_color, 2)
        else:
            self.status = "No Person"
            cv2.putText(frame, f"Cam: {camera_name}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(frame, self.status, (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)

        return frame

    def draw_overlay(self, frame, camera_name="Unknown"):
        """Draw the last known status overlay without running AI inference."""
        cv2.putText(frame, f"Cam: {camera_name}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(frame, f"Status: {self.status}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, self.color, 3)
        return frame
