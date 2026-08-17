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


class _CameraState:
    """Per-camera (or per-sub-frame) detection state."""
    def __init__(self):
        self.fall_counter = 0
        self.status = 'normal'
        self.color = (0, 255, 0)
        self._fall_callback_fired = False
        self.persons_data = []
        self.debug_txt = ""
        self.last_intruder_msg = ""
        self.last_intruder_color = (255, 255, 255)
        self.last_face_check_time = 0


def _draw_text_with_badge(img, text, pos, font_scale=0.6, text_color=(255, 255, 255), bg_color=(0, 0, 0), thickness=2, padding=4):
    """Draw high-contrast text with background box so it's always clear and readable."""
    x, y = pos
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    
    # Draw background rectangle
    cv2.rectangle(
        img,
        (x - padding, y - text_h - padding),
        (x + text_w + padding, y + baseline + padding),
        bg_color,
        cv2.FILLED
    )
    # Draw text
    cv2.putText(img, text, (x, y), font, font_scale, text_color, thickness, cv2.LINE_AA)
    return text_h + baseline + padding * 2


class FallDetector:
    def __init__(self, yolo_path=None, rf_path=None, conf_threshold=0.5, fall_trigger_frames=6, on_fall_callback=None, on_intruder_callback=None):
        if yolo_path is None:
            yolo_path = os.path.join(_PROJECT_ROOT, "Tools", "yolov8n-pose.pt")
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

        self._camera_states = {}

        self.fall_counter = 0
        self.status = 'normal'
        self.color = (0, 255, 0)
        self.last_kpts_xyn = None
        self.last_box_xyxyn = None
        self.last_pose_name = "Unknown"
        self.last_ai_conf = 0.0
        self.last_debug_txt = ""

        self.on_fall_callback = on_fall_callback
        self.on_intruder_callback = on_intruder_callback
        self._fall_callback_fired = False
        
        try:
            pygame.mixer.init()
        except Exception as e:
            print(f"Failed to initialize pygame mixer: {e}")
            
        self.last_alert_time = 0.0
        self.last_intruder_alert_time = 0.0
        self.alert_cooldown = 10
        
        self.face_service = None
        self._face_service_loaded = False
        
        self.last_face_check_time = 0
        self.last_intruder_msg = ""
        self.last_intruder_color = (255, 255, 255)
        
        # YOLO input size: 416 gives much better skeleton accuracy without losing speed
        self._yolo_input_size = 416

    def _get_state(self, camera_id):
        if camera_id not in self._camera_states:
            self._camera_states[camera_id] = _CameraState()
        return self._camera_states[camera_id]

    def _get_face_service(self):
        if not self._face_service_loaded:
            self._face_service_loaded = True
            try:
                from src.services.face_recognition_service import FaceRecognitionService
                self.face_service = FaceRecognitionService()
            except Exception as e:
                self.face_service = None
        return self.face_service

    def _analyze_skeleton_geometry(self, kpts, bw, bh):
        """Robust geometric analysis from detected keypoints.
        
        Works even if several keypoints are missing or occluded.
        """
        # Filter valid keypoints
        valid = [(kpts[i][0], kpts[i][1], i) for i in range(17) if kpts[i][0] > 0.01 and kpts[i][1] > 0.01]
        if len(valid) < 4:
            # Fallback to bbox aspect ratio
            ar = bw / bh if bh > 0 else 0
            return {
                'is_horizontal': ar > 1.25,
                'aspect_ratio': ar,
                'torso_angle': 90.0 if ar > 1.25 else 0.0,
                'kpt_span_ratio': ar,
                'valid_count': len(valid)
            }
        
        xs = [p[0] for p in valid]
        ys = [p[1] for p in valid]
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)
        kpt_span_ratio = (x_span / y_span) if y_span > 0.01 else 2.0
        ar = bw / bh if bh > 0 else kpt_span_ratio

        # Find any shoulder (5, 6) and any hip (11, 12)
        shoulders = [kpts[i] for i in [5, 6] if kpts[i][0] > 0.01 and kpts[i][1] > 0.01]
        hips = [kpts[i] for i in [11, 12] if kpts[i][0] > 0.01 and kpts[i][1] > 0.01]

        torso_angle = None
        if shoulders and hips:
            s_x = np.mean([p[0] for p in shoulders])
            s_y = np.mean([p[1] for p in shoulders])
            h_x = np.mean([p[0] for p in hips])
            h_y = np.mean([p[1] for p in hips])
            dx = abs(s_x - h_x)
            dy = abs(s_y - h_y)
            torso_angle = np.degrees(np.arctan2(dx, dy)) if dy > 0.005 else 90.0
        else:
            torso_angle = 90.0 if (ar > 1.25 or kpt_span_ratio > 1.2) else 0.0

        # Lying criteria:
        # 1. Bounding box width > height (aspect_ratio > 1.25)
        # 2. Keypoints span wider than tall (kpt_span_ratio > 1.2)
        # 3. Torso angle > 45 degrees from vertical
        is_horizontal = (ar > 1.25) or (kpt_span_ratio > 1.2) or (torso_angle is not None and torso_angle > 50)

        return {
            'is_horizontal': is_horizontal,
            'aspect_ratio': ar,
            'torso_angle': torso_angle,
            'kpt_span_ratio': kpt_span_ratio,
            'valid_count': len(valid)
        }

    def async_play_alert(self, camera_name):
        current_time = time.time()
        if current_time - self.last_alert_time < self.alert_cooldown:
            return
            
        self.last_alert_time = current_time
        
        def _speak():
            text = f"แจ้งเตือน ตรวจพบการล้มที่ {camera_name}"
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

    def process_frame(self, frame, camera_name="Unknown", camera_id=None):
        """Process a frame for multi-person fall detection."""
        if camera_id is None:
            camera_id = camera_name
        state = self._get_state(camera_id)

        if self.fall_model is None:
            _draw_text_with_badge(frame, "Model Error", (20, 50), text_color=(0, 0, 255))
            return frame

        original_frame = frame.copy()

        h, w = frame.shape[:2]
        scale = self._yolo_input_size / max(h, w)
        small_w = int(w * scale)
        small_h = int(h * scale)
        small_frame = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        
        results = self.pose_model(small_frame, verbose=False, conf=self.conf_threshold)

        if results[0].keypoints is not None and len(results[0].keypoints) > 0:
             annotated_small = results[0].plot()
             frame = cv2.resize(annotated_small, (w, h), interpolation=cv2.INTER_LINEAR)

             num_persons = len(results[0].keypoints)
             any_falling = False
             persons_data = []

             for i in range(num_persons):
                 kpts = results[0].keypoints.xyn[i].cpu().numpy()
                 row = kpts.flatten().tolist()

                 # Predict pose with RF
                 prediction = self.fall_model.predict([row])[0]
                 prob = self.fall_model.predict_proba([row])[0]
                 ai_confidence = prob[prediction]
                 pose_name = self.pose_labels.get(prediction, "Unknown")

                 box = results[0].boxes.xywh[i].cpu().numpy()
                 box_xyxyn = results[0].boxes.xyxyn[i].cpu().numpy()
                 bw, bh = box[2], box[3]

                 # Geometric analysis
                 geo = self._analyze_skeleton_geometry(kpts, bw, bh)
                 ar = geo['aspect_ratio']
                 is_horizontal = geo['is_horizontal']

                 # ═══ Robust Fall Decision Logic ═══
                 is_falling = False

                 if is_horizontal and ar > 1.25:
                     # ร่างกายอยู่ในแนวราบ (กว้างกว่าสูง) -> ล้ม / นอนกับพื้น
                     is_falling = True
                     label_text = f"FALL DETECTED (Lying AR={ar:.1f})"
                 elif prediction == 4 and ai_confidence > 0.5:
                     # AI RF model มั่นใจว่าล้ม
                     is_falling = True
                     label_text = f"FALL DETECTED ({ai_confidence*100:.0f}%)"
                 elif ar < 0.75:
                     # สูงกว่ากว้างชัดเจน -> ยืน/เดิน
                     is_falling = False
                     label_text = f"Standing/Walking ({pose_name})"
                 elif 0.75 <= ar <= 1.25:
                     # ก้ำกึ่ง -> นั่ง
                     is_falling = False
                     label_text = f"Sitting ({pose_name})"
                 else:
                     is_falling = False
                     label_text = f"{pose_name} ({ai_confidence*100:.0f}%)"

                 if is_falling:
                     any_falling = True

                 persons_data.append({
                     'kpts_xyn': kpts,
                     'box_xyxyn': box_xyxyn,
                     'pose_name': "Fall" if is_falling else pose_name,
                     'ai_conf': float(ai_confidence),
                     'is_falling': is_falling,
                     'label_text': label_text,
                 })

             # Update fall counter
             if any_falling:
                 state.fall_counter += 1
             else:
                 state.fall_counter = max(0, state.fall_counter - 1)

             if state.fall_counter >= self.fall_trigger_frames:
                state.status = '!!! FALL DETECTED !!!'
                state.color = (0, 0, 255) # Red
                self.async_play_alert(camera_name)
                if self.on_fall_callback and not state._fall_callback_fired:
                    state._fall_callback_fired = True
                    try:
                        self.on_fall_callback(camera_name, frame, time.time())
                    except Exception as e:
                        print(f"❌ Fall callback error: {e}")
             else:
                 state.status = 'normal'
                 state.color = (0, 255, 0) # Green
                 state._fall_callback_fired = False

             state.persons_data = persons_data

             # Backward compat
             self.fall_counter = state.fall_counter
             self.status = state.status
             self.color = state.color
             self._fall_callback_fired = state._fall_callback_fired

             # Draw clear person badges on frame
             self._draw_overlay_elements(frame, state, camera_name)

        else:
            state.status = "No Person"
            state.persons_data = []
            state.fall_counter = 0
            state._fall_callback_fired = False
            self.status = "No Person"
            _draw_text_with_badge(frame, f"Cam: {camera_name} | No Person", (15, 30), font_scale=0.6, text_color=(0, 255, 255))

        return frame

    def _draw_overlay_elements(self, frame, state, camera_name):
        """Draw clean, non-overlapping, high-contrast overlay on the frame."""
        h, w = frame.shape[:2]
        
        # 1. Draw Bounding Boxes and Person Badges
        for p_idx, person in enumerate(state.persons_data):
            box = person['box_xyxyn']
            x1, y1, x2, y2 = int(box[0]*w), int(box[1]*h), int(box[2]*w), int(box[3]*h)
            
            p_color = (0, 0, 255) if person['is_falling'] else (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), p_color, 2)

            # Draw Person Tag above box
            tag_text = f"P{p_idx+1}: {'FALL' if person['is_falling'] else person['pose_name']}"
            tag_bg = (0, 0, 180) if person['is_falling'] else (0, 140, 0)
            tag_y = max(y1 - 6, 20)
            _draw_text_with_badge(frame, tag_text, (x1, tag_y), font_scale=0.55, text_color=(255, 255, 255), bg_color=tag_bg, thickness=2)

        # 2. Draw Top Status Banner (at Y=30 to avoid card header)
        status_bg = (0, 0, 180) if state.status.startswith('!') else (20, 20, 20)
        status_text = f"Status: {state.status} | Persons: {len(state.persons_data)} | Trigger: {state.fall_counter}/{self.fall_trigger_frames}"
        _draw_text_with_badge(frame, status_text, (15, 30), font_scale=0.55, text_color=state.color, bg_color=status_bg, thickness=2)

    def draw_overlay(self, frame, camera_name="Unknown", camera_id=None):
        """Draw cached overlay for fast 30FPS rendering without AI."""
        if camera_id is None:
            camera_id = camera_name
        state = self._get_state(camera_id)
        h, w = frame.shape[:2]

        # Draw person boxes and skeleton dots
        for p_idx, person in enumerate(state.persons_data):
            box = person['box_xyxyn']
            x1, y1, x2, y2 = int(box[0]*w), int(box[1]*h), int(box[2]*w), int(box[3]*h)
            p_color = (0, 0, 255) if person['is_falling'] else (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), p_color, 2)
            
            for pt in person['kpts_xyn']:
                px, py = int(pt[0]*w), int(pt[1]*h)
                if px > 0 and py > 0:
                    cv2.circle(frame, (px, py), 3, (0, 255, 255), -1)

            tag_text = f"P{p_idx+1}: {'FALL' if person['is_falling'] else person['pose_name']}"
            tag_bg = (0, 0, 180) if person['is_falling'] else (0, 140, 0)
            tag_y = max(y1 - 6, 20)
            _draw_text_with_badge(frame, tag_text, (x1, tag_y), font_scale=0.55, text_color=(255, 255, 255), bg_color=tag_bg, thickness=2)

        # Draw Status Banner
        status_bg = (0, 0, 180) if state.status.startswith('!') else (20, 20, 20)
        status_text = f"Status: {state.status} | Persons: {len(state.persons_data)} | Trigger: {state.fall_counter}/{self.fall_trigger_frames}"
        _draw_text_with_badge(frame, status_text, (15, 30), font_scale=0.55, text_color=state.color, bg_color=status_bg, thickness=2)

        return frame
