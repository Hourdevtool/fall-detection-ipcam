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
    def __init__(self, yolo_path=None, rf_path=None, conf_threshold=0.7, fall_trigger_frames=10):
        # ใช้ absolute path เพื่อให้ subprocess หาไฟล์เจอเสมอ
        if yolo_path is None:
            yolo_path = os.path.join(_PROJECT_ROOT,"Tools", "yolov8n-pose.pt")
        if rf_path is None:
            rf_path = os.path.join(_PROJECT_ROOT, "Tools", "fall_detect_model.pkl")

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
        
        # Audio playback initialization
        try:
            pygame.mixer.init()
        except Exception as e:
            print(f"Failed to initialize pygame mixer: {e}")
            
        self.last_alert_time = 0.0
        self.alert_cooldown = 10  # seconds between alerts

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

    def process_frame(self, frame, camera_name="Unknown"):
        if self.fall_model is None:
            cv2.putText(frame, "Model Error", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return frame

        results = self.pose_model(frame, verbose=False, conf=self.conf_threshold)

        if results[0].keypoints is not None and len(results[0].keypoints) > 0:
             # Draw skeleton
             frame = results[0].plot()
            
             # Get keypoints
             kpts = results[0].keypoints.xyn[0].cpu().numpy()
             row = kpts.flatten().tolist()

             # Predict using RF model
             prediction = self.fall_model.predict([row])[0]
             prob = self.fall_model.predict_proba([row])[0]
             ai_confidence = prob[prediction]
              
             box = results[0].boxes.xywh[0].cpu().numpy()
             w, h = box[2], box[3]
             aspect_ratio = w / h if h > 0 else 0
             is_falling = False
             debug_txt = ""

             # Logic verification
             if aspect_ratio < 0.90:
                is_falling = False
                debug_txt = f"Geo: Force Normal (Standing {aspect_ratio:.2f})"
             else:
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

             if is_falling:
                 self.fall_counter += 1
             else:
                 self.fall_counter = 0

             if self.fall_counter >= self.fall_trigger_frames:
                self.status = '!!! FALL DETECTED !!!'
                self.color = (0, 0, 255) # Red
                self.async_play_alert(camera_name)
             else:
                 self.status = 'normal'
                 self.color = (0, 255, 0) # Green
            
             cv2.putText(frame, f"Cam: {camera_name}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
             cv2.putText(frame, f"Status: {self.status}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, self.color, 3)
             cv2.putText(frame, f"Logic: {debug_txt}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
             cv2.putText(frame, f"Count: {self.fall_counter}/{self.fall_trigger_frames}", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
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
