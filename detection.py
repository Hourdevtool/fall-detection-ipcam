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
        self.is_checking_face = False
        self.unknown_person_start_time = 0
        self._intruder_callback_fired = False


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
    def __init__(self, yolo_path=None, rf_path=None, conf_threshold=0.65, fall_trigger_frames=6, on_fall_callback=None, on_intruder_callback=None):
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
        
        # YOLO input size: 640 gives much higher accuracy for small/lying skeletons on the floor
        self._yolo_input_size = 640

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

    def _analyze_skeleton_geometry(self, kpts, bw, bh, box_xyxyn=None):
        """Robust geometric analysis from detected keypoints."""
        valid = [(kpts[i][0], kpts[i][1], i) for i in range(17) if kpts[i][0] > 0.01 and kpts[i][1] > 0.01]
        
        # Estimate head_y (average Y of nose/eyes/ears/shoulders)
        head_kpts = [kpts[i][1] for i in range(7) if kpts[i][0] > 0.01 and kpts[i][1] > 0.01]
        head_y = np.mean(head_kpts) if head_kpts else (box_xyxyn[1] if box_xyxyn is not None else 0.5)

        # Check body keypoints (shoulders 5,6 / hips 11,12 / knees 13,14 / ankles 15,16)
        body_kpts_count = sum(1 for i in range(5, 17) if kpts[i][0] > 0.01 and kpts[i][1] > 0.01)

        if len(valid) < 4:
            ar = bw / bh if bh > 0 else 0
            return {
                'is_horizontal': False,
                'aspect_ratio': ar,
                'torso_angle': None,
                'kpt_span_ratio': ar,
                'head_y': head_y,
                'valid_count': len(valid),
                'body_kpts_count': body_kpts_count
            }
        
        xs = [p[0] for p in valid]
        ys = [p[1] for p in valid]
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)
        kpt_span_ratio = (x_span / y_span) if y_span > 0.01 else 2.0
        ar = bw / bh if bh > 0 else kpt_span_ratio

        # Find shoulders (5, 6) and hips (11, 12)
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
            # 0 deg = vertical standing/sitting, 90 deg = horizontal lying
            torso_angle = np.degrees(np.arctan2(dx, dy)) if dy > 0.005 else 90.0
        else:
            torso_angle = None

        is_horizontal = bool(torso_angle is not None and torso_angle > 55)

        return {
            'is_horizontal': is_horizontal,
            'aspect_ratio': ar,
            'torso_angle': torso_angle,
            'kpt_span_ratio': kpt_span_ratio,
            'head_y': head_y,
            'valid_count': len(valid),
            'body_kpts_count': body_kpts_count
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
                 y1, y2 = box_xyxyn[1], box_xyxyn[3]

                 # Geometric analysis
                 geo = self._analyze_skeleton_geometry(kpts, bw, bh, box_xyxyn)
                 ar = geo['aspect_ratio']
                 head_y = geo['head_y']
                 torso_angle = geo['torso_angle']
                 body_kpts_count = geo['body_kpts_count']
                 valid_count = geo['valid_count']

                 if results[0].keypoints.conf is not None:
                     kpts_conf = results[0].keypoints.conf[i].cpu().numpy()
                 else:
                     kpts_conf = np.ones(17)

                 # Strict Lower Body Keypoint Check (only count if confidence > 0.35)
                 has_hips = any(kpts_conf[j] > 0.35 and kpts[j][0] > 0.01 for j in [11, 12])
                 has_legs = any(kpts_conf[j] > 0.35 and kpts[j][0] > 0.01 for j in [13, 14, 15, 16])
                 has_lower_body = bool(has_hips or has_legs)

                 # Head keypoints count (0:nose, 1,2:eyes, 3,4:ears)
                 head_kpts_count = sum(1 for j in range(5) if kpts_conf[j] > 0.35 and kpts[j][0] > 0.01)

                 # Head vs Hip Y check
                 shoulders_y = [kpts[j][1] for j in [5, 6] if kpts_conf[j] > 0.35 and kpts[j][0] > 0.01]
                 hips_y = [kpts[j][1] for j in [11, 12] if kpts_conf[j] > 0.35 and kpts[j][0] > 0.01]

                 # Close-up face/upper-chest check (no lower body detected, or head is dominant)
                 is_face_or_upper_closeup = bool(not has_lower_body or (not has_hips and head_kpts_count >= 2))

                 # Lying flat on floor check (must have lower body, hips, and be positioned in floor zone)
                 is_lying_in_floor_zone = bool(has_lower_body and has_hips and y1 > 0.45 and (bh < 0.50 or ar > 1.25))

                 # Head inversion on floor (head lower than hips by > 0.10)
                 is_head_lower_than_hips = bool(
                     has_lower_body and has_hips and shoulders_y and hips_y and 
                     (np.mean(shoulders_y) > np.mean(hips_y) + 0.10)
                 )

                 # Upright posture (sitting/standing with head above hips and torso angle < 50)
                 is_standing_or_sitting_upright = bool((y1 < 0.40 or head_y < 0.42) and (torso_angle is not None and torso_angle < 50))

                 # ═══ Enhanced & Robust Fall Decision Logic ═══
                 is_falling = False

                 if is_face_or_upper_closeup:
                     # Face or Upper Body Close-up (NEVER a fall!)
                     is_falling = False
                     label_text = "Close-up"
                 elif is_lying_in_floor_zone or is_head_lower_than_hips:
                     # Lying flat on floor (on back, on stomach, or head-first) -> FALL
                     is_falling = True
                     label_text = "FALL (Floor)"
                 elif prediction == 4 and ai_confidence > 0.45 and has_lower_body:
                     # AI model confident it's a fall
                     is_falling = True
                     label_text = f"FALL (AI {ai_confidence*100:.0f}%)"
                 elif torso_angle is not None and torso_angle > 55 and has_lower_body and y2 > 0.35:
                     # Body torso tilted horizontally -> Fall
                     is_falling = True
                     label_text = "FALL (Angle)"
                 elif is_standing_or_sitting_upright:
                     # Standing / Walking / Sitting upright
                     is_falling = False
                     label_text = f"{pose_name}"
                 elif ar < 0.75:
                     # Tall box -> Standing/Walking
                     is_falling = False
                     label_text = f"{pose_name}"
                 else:
                     is_falling = False
                     label_text = f"{pose_name}"

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

             # ═══ Face Recognition / Intruder Detection Pipeline ═══
             intruder_mode_on = os.environ.get("INTRUDER_DETECTION", "0") == "1"
             if intruder_mode_on:
                 face_svc = self._get_face_service()
                 if face_svc:
                     cur_time = time.time()
                     if cur_time - state.last_face_check_time > 1.5 and not state.is_checking_face:
                         state.is_checking_face = True
                         state.last_face_check_time = cur_time
                         
                         def _async_face_check(crop_img, c_name, c_id):
                             try:
                                 is_intruder, msg = face_svc.detect_intruder(crop_img)
                                 c_state = self._get_state(c_id)
                                 
                                 if "Known:" in msg:
                                     name = msg.replace("Known:", "").split("(")[0].strip()
                                     c_state.last_intruder_msg = f"Known ({name})"
                                     c_state.last_intruder_color = (0, 255, 0)
                                     c_state.unknown_person_start_time = 0
                                     c_state._intruder_callback_fired = False
                                 elif is_intruder:
                                     c_state.last_intruder_msg = "Intruder Detected!"
                                     c_state.last_intruder_color = (0, 0, 255)
                                     self.async_play_intruder_alert(c_name)
                                     if self.on_intruder_callback and not c_state._intruder_callback_fired:
                                         c_state._intruder_callback_fired = True
                                         try:
                                             self.on_intruder_callback(c_name, crop_img, time.time())
                                         except Exception as e:
                                             print(f"❌ Intruder callback error: {e}")
                                 else:
                                     # Face covered, wearing hat, or no registered faces in DB
                                     if not face_svc.known_embeddings:
                                         c_state.last_intruder_msg = "No Registered Face"
                                         c_state.last_intruder_color = (0, 255, 255)
                                     else:
                                         if not c_state.unknown_person_start_time:
                                             c_state.unknown_person_start_time = time.time()
                                         
                                         elapsed = time.time() - c_state.unknown_person_start_time
                                         if elapsed > 4.0:
                                             c_state.last_intruder_msg = "Intruder (Masked)!"
                                             c_state.last_intruder_color = (0, 0, 255)
                                             self.async_play_intruder_alert(c_name)
                                             if self.on_intruder_callback and not c_state._intruder_callback_fired:
                                                 c_state._intruder_callback_fired = True
                                                 try:
                                                     self.on_intruder_callback(c_name, crop_img, time.time())
                                                 except Exception as e:
                                                     print(f"❌ Intruder callback error: {e}")
                                         else:
                                             c_state.last_intruder_msg = "Verifying Face..."
                                             c_state.last_intruder_color = (0, 165, 255)
                             except Exception as e:
                                 pass
                             finally:
                                 self._get_state(c_id).is_checking_face = False

                         threading.Thread(target=_async_face_check, args=(original_frame.copy(), camera_name, camera_id), daemon=True).start()
             else:
                 state.last_intruder_msg = ""
                 state.unknown_person_start_time = 0
                 state._intruder_callback_fired = False

             # Update fall counter (decay slightly slower to prevent flickering when lying on floor)
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
                 state.status = 'Normal'
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
            state.unknown_person_start_time = 0
            state.last_intruder_msg = ""
            self.status = "No Person"
            _draw_text_with_badge(frame, f"Cam: {camera_name} | No Person", (15, 22), font_scale=0.50, text_color=(0, 255, 255), thickness=1)

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

            # Draw Person Tag — position smartly so it never overlaps the top banner
            tag_text = f"P{p_idx+1}: {person['label_text']}"
            tag_bg = (0, 0, 180) if person['is_falling'] else (0, 140, 0)
            
            if y1 < 45:
                tag_y = y1 + 18
                tag_x = x1 + 4
            else:
                tag_y = y1 - 5
                tag_x = x1
                
            _draw_text_with_badge(frame, tag_text, (tag_x, tag_y), font_scale=0.48, text_color=(255, 255, 255), bg_color=tag_bg, thickness=1, padding=3)

        # 2. Draw Top Status Banner
        status_bg = (0, 0, 180) if state.status.startswith('!') else (20, 20, 20)
        status_text = f"Status: {state.status} | Persons: {len(state.persons_data)}"
        if state.fall_counter > 0 and state.status == 'Normal':
            status_text += f" (Trigger: {state.fall_counter}/{self.fall_trigger_frames})"
            
        _draw_text_with_badge(frame, status_text, (15, 22), font_scale=0.50, text_color=state.color, bg_color=status_bg, thickness=1, padding=3)

        # 3. Draw Security / Intruder Banner if enabled
        if state.last_intruder_msg and os.environ.get("INTRUDER_DETECTION", "0") == "1":
            sec_bg = (0, 0, 180) if "Intruder" in state.last_intruder_msg else (20, 20, 20)
            _draw_text_with_badge(frame, f"Security: {state.last_intruder_msg}", (15, 46), font_scale=0.48, text_color=state.last_intruder_color, bg_color=sec_bg, thickness=1, padding=3)

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

            tag_text = f"P{p_idx+1}: {person['label_text']}"
            tag_bg = (0, 0, 180) if person['is_falling'] else (0, 140, 0)
            
            if y1 < 45:
                tag_y = y1 + 18
                tag_x = x1 + 4
            else:
                tag_y = y1 - 5
                tag_x = x1
                
            _draw_text_with_badge(frame, tag_text, (tag_x, tag_y), font_scale=0.48, text_color=(255, 255, 255), bg_color=tag_bg, thickness=1, padding=3)

        # Draw Status Banner
        status_bg = (0, 0, 180) if state.status.startswith('!') else (20, 20, 20)
        status_text = f"Status: {state.status} | Persons: {len(state.persons_data)}"
        if state.fall_counter > 0 and state.status == 'Normal':
            status_text += f" (Trigger: {state.fall_counter}/{self.fall_trigger_frames})"
            
        _draw_text_with_badge(frame, status_text, (15, 22), font_scale=0.50, text_color=state.color, bg_color=status_bg, thickness=1, padding=3)

        # Draw Security / Intruder Banner if enabled
        if state.last_intruder_msg and os.environ.get("INTRUDER_DETECTION", "0") == "1":
            sec_bg = (0, 0, 180) if "Intruder" in state.last_intruder_msg else (20, 20, 20)
            _draw_text_with_badge(frame, f"Security: {state.last_intruder_msg}", (15, 46), font_scale=0.48, text_color=state.last_intruder_color, bg_color=sec_bg, thickness=1, padding=3)

        return frame
