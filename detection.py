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
import sys
import tempfile

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.services.pose_features import (  # noqa: E402
    POSE_FEATURE_DIM,
    extract_pose_features,
    safe_torso_angle_and_dy,
)


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
        self._no_fall_frames = 0  # consecutive frames with no fall (for slow decay)


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
    def __init__(self, yolo_path=None, rf_path=None, conf_threshold=0.45, fall_trigger_frames=4, on_fall_callback=None, on_intruder_callback=None):
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
        
        print(f"Loading Pose Classification model from {rf_path}...")
        try:
             self.fall_model = joblib.load(self.rf_path)
             if hasattr(self.fall_model, "n_jobs"):
                 # Single-threaded predict avoids joblib IPC overhead (~70ms -> ~6-12ms)
                 self.fall_model.n_jobs = 1
        except Exception as e:
             print(f"❌ Could not load pose model from {self.rf_path}. Error: {e}")
             self.fall_model = None

        self._use_pose_features = bool(
            self.fall_model is not None
            and getattr(self.fall_model, "n_features_in_", 34) == POSE_FEATURE_DIM
        )
        self._model_classes = (
            np.asarray(self.fall_model.classes_)
            if self.fall_model is not None and hasattr(self.fall_model, "classes_")
            else np.array([0, 1, 2, 3, 4])
        )
        self._infer_lock = threading.Lock()
        self._state_lock = threading.Lock()
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
        with self._state_lock:
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

    def _analyze_skeleton_geometry(self, kpts_xy, bw, bh, box_xyxyn=None, kpts_conf=None, min_conf=0.30):
        """Robust geometric analysis in 1:1 pixel coordinates (avoids aspect distortion & occluded-side tilt)."""
        kpts_arr = np.asarray(kpts_xy, dtype=np.float32)
        nonzero = (np.abs(kpts_arr[:, 0]) > 1e-4) | (np.abs(kpts_arr[:, 1]) > 1e-4)
        if kpts_conf is not None:
            valid_mask = (np.asarray(kpts_conf, dtype=np.float32) >= min_conf) & nonzero
        else:
            valid_mask = nonzero

        valid_pts = [(float(kpts_arr[i][0]), float(kpts_arr[i][1]), i) for i in range(17) if valid_mask[i]]

        # Normalized head_y (0..1) if box provided, otherwise from keypoints
        head_kpts = [kpts_arr[i][1] for i in range(7) if valid_mask[i]]
        head_y = float(np.mean(head_kpts)) if head_kpts else (float(box_xyxyn[1]) if box_xyxyn is not None else 0.5)
        body_kpts_count = sum(1 for i in range(5, 17) if valid_mask[i])
        ar = float(bw / bh) if bh > 0 else 0.0

        if len(valid_pts) < 4:
            return {
                'is_horizontal': False,
                'aspect_ratio': ar,
                'torso_angle': None,
                'dy_signed': 0.0,
                'torso_len': 0.0,
                'kpt_span_ratio': ar,
                'head_y': head_y,
                'valid_count': len(valid_pts),
                'body_kpts_count': body_kpts_count,
            }

        xs = [p[0] for p in valid_pts]
        ys = [p[1] for p in valid_pts]
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)
        kpt_span_ratio = (x_span / y_span) if y_span > 1.0 else 2.0
        if bh <= 0:
            ar = kpt_span_ratio

        torso_angle, dy_signed, torso_len = safe_torso_angle_and_dy(kpts_arr, valid_mask)
        is_horizontal = bool(torso_angle is not None and torso_angle > 55)

        return {
            'is_horizontal': is_horizontal,
            'aspect_ratio': ar,
            'torso_angle': torso_angle,
            'dy_signed': dy_signed,
            'torso_len': torso_len,
            'kpt_span_ratio': kpt_span_ratio,
            'head_y': head_y,
            'valid_count': len(valid_pts),
            'body_kpts_count': body_kpts_count,
        }

    def _classify_person_pose(self, prediction, ai_confidence, kpts_xyn, kpts_xy, kpts_conf, box_xywh, box_xyxyn):
        """Decide (is_falling, label_text) combining ML probabilities with occlusion-aware geometry."""
        pose_name = self.pose_labels.get(int(prediction), "Unknown")
        bw, bh = float(box_xywh[2]), float(box_xywh[3])
        y1, y2 = float(box_xyxyn[1]), float(box_xyxyn[3])
        bh_norm = max(0.0, y2 - y1)

        geo = self._analyze_skeleton_geometry(kpts_xy, bw, bh, box_xyxyn, kpts_conf=kpts_conf)
        ar = geo['aspect_ratio']
        torso_angle = geo['torso_angle']
        dy_signed = geo['dy_signed']

        def _kp_ok(j):
            return bool(kpts_conf[j] > 0.35 and (kpts_xyn[j][0] > 0.01 or kpts_xyn[j][1] > 0.01))

        has_hips = any(_kp_ok(j) for j in (11, 12))
        has_legs = any(_kp_ok(j) for j in (13, 14, 15, 16))
        has_lower_body = bool(has_hips or has_legs)
        head_kpts_count = sum(1 for j in range(5) if _kp_ok(j))

        shoulders_y_norm = [float(kpts_xyn[j][1]) for j in (5, 6) if kpts_conf[j] > 0.40 and (kpts_xyn[j][0] > 0.01 or kpts_xyn[j][1] > 0.01)]
        hips_y_norm = [float(kpts_xyn[j][1]) for j in (11, 12) if kpts_conf[j] > 0.40 and (kpts_xyn[j][0] > 0.01 or kpts_xyn[j][1] > 0.01)]
        knees_y_norm = [float(kpts_xyn[j][1]) for j in (13, 14) if _kp_ok(j)]

        is_face_or_upper_closeup = bool(not has_lower_body or (not has_hips and head_kpts_count >= 2))
        # Upright/partially occluded behind table/furniture: legs hidden & torso not inverted/horizontal
        is_table_occluded_upright = bool(
            not has_legs
            and (torso_angle is None or torso_angle < 58.0)
            and (dy_signed >= 0.0 or not (shoulders_y_norm and hips_y_norm))
        )
        is_head_lower_than_hips = bool(
            has_lower_body and has_hips and shoulders_y_norm and hips_y_norm
            and (np.mean(shoulders_y_norm) > np.mean(hips_y_norm) + 0.08)
        )
        is_upright_chair = bool(
            prediction in (1, 2) and ai_confidence >= 0.45
            and torso_angle is not None and torso_angle < 45.0
        )
        is_standing_bend = bool(
            prediction in (1, 3) and ai_confidence >= 0.45
            and has_legs and bh_norm >= 0.48
            and (
                y1 <= 0.48
                or (shoulders_y_norm and knees_y_norm and hips_y_norm and np.mean(knees_y_norm) > np.mean(hips_y_norm) + 0.04)
            )
        )
        is_lying_in_floor_zone = bool(
            has_hips and has_legs and not is_upright_chair and not is_standing_bend
            and y1 > 0.45 and bh_norm < 0.52
            and (
                ar > 1.25
                or (torso_angle is not None and torso_angle > 50.0)
                or (prediction == 4 and ai_confidence >= 0.42)
                or (y1 > 0.50 and bh_norm < 0.46 and torso_angle is None)
            )
        )
        ai_fall_allowed = bool(
            prediction == 4
            and has_lower_body
            and (has_legs or (torso_angle is not None and torso_angle > 62.0))
            and (
                (ai_confidence >= 0.50 and (y1 >= 0.38 or (torso_angle is not None and torso_angle >= 42.0) or ar > 1.15))
                or (ai_confidence >= 0.72 and ar > 1.05)
            )
        )

        if is_face_or_upper_closeup:
            return False, ("Close-up" if not has_lower_body else pose_name), geo
        if is_head_lower_than_hips:
            return True, "FALL (Floor)", geo
        if is_table_occluded_upright:
            return False, (pose_name if pose_name != "Fall" else "Sit"), geo
        if is_lying_in_floor_zone:
            return True, "FALL (Floor)", geo
        if ai_fall_allowed:
            return True, f"FALL (AI {ai_confidence*100:.0f}%)", geo
        if (
            not is_standing_bend
            and torso_angle is not None and torso_angle > 58.0
            and has_hips and (has_legs or torso_angle > 68.0)
            and y2 > 0.35 and bh_norm < 0.72
        ):
            return True, "FALL (Angle)", geo

        return False, pose_name, geo

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

    def process_frame(self, frame, camera_name="Unknown", camera_id=None, draw=True):
        """Process a frame for multi-person fall detection.

        Set draw=False in live RTSP pipelines where a separate display thread draws
        cached overlays via draw_overlay(), avoiding redundant plot()/resize overhead.
        """
        if camera_id is None:
            camera_id = camera_name
        state = self._get_state(camera_id)

        if self.fall_model is None:
            if draw:
                _draw_text_with_badge(frame, "Model Error", (20, 50), text_color=(0, 0, 255))
            return frame

        source_frame = frame
        h, w = frame.shape[:2]
        max_dim = max(h, w)
        if max_dim > self._yolo_input_size:
            scale = self._yolo_input_size / max_dim
            infer_frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
        else:
            infer_frame = frame

        with self._infer_lock:
            results = self.pose_model(
                infer_frame,
                verbose=False,
                conf=self.conf_threshold,
            )

        if results[0].keypoints is not None and len(results[0].keypoints) > 0:
             if draw:
                 annotated = results[0].plot()
                 frame = cv2.resize(annotated, (w, h), interpolation=cv2.INTER_LINEAR) if infer_frame is not frame else annotated

             num_persons = len(results[0].keypoints)
             any_falling = False
             persons_data = []

             all_kpts_xyn = results[0].keypoints.xyn.cpu().numpy()
             all_kpts_xy = results[0].keypoints.xy.cpu().numpy()
             if results[0].keypoints.conf is not None:
                 all_kpts_conf = results[0].keypoints.conf.cpu().numpy()
             else:
                 all_kpts_conf = np.ones((num_persons, 17), dtype=np.float32)

             all_boxes_xywh = results[0].boxes.xywh.cpu().numpy()
             all_boxes_xyxyn = results[0].boxes.xyxyn.cpu().numpy()

             # Batch ML inference using single predict_proba call
             if self._use_pose_features:
                 all_rows = np.asarray(
                     [extract_pose_features(all_kpts_xy[i], all_kpts_conf[i]) for i in range(num_persons)],
                     dtype=np.float32,
                 )
             else:
                 all_rows = np.asarray(
                     [all_kpts_xyn[i].flatten() for i in range(num_persons)],
                     dtype=np.float32,
                 )

             with self._infer_lock:
                 all_probs = self.fall_model.predict_proba(all_rows)

             best_col_idx = np.argmax(all_probs, axis=1)
             all_predictions = self._model_classes[best_col_idx]
             all_confidences = all_probs[np.arange(num_persons), best_col_idx]

             for i in range(num_persons):
                 kpts = all_kpts_xyn[i]
                 kpts_xy = all_kpts_xy[i]
                 kpts_conf = all_kpts_conf[i]
                 prediction = int(all_predictions[i])
                 ai_confidence = float(all_confidences[i])
                 pose_name = self.pose_labels.get(prediction, "Unknown")

                 box = all_boxes_xywh[i]
                 box_xyxyn = all_boxes_xyxyn[i]

                 is_falling, label_text, _geo = self._classify_person_pose(
                     prediction, ai_confidence, kpts, kpts_xy, kpts_conf, box, box_xyxyn
                 )

                 if is_falling:
                     any_falling = True

                 persons_data.append({
                     'kpts_xyn': kpts,
                     'box_xyxyn': box_xyxyn,
                     'pose_name': "Fall" if is_falling else pose_name,
                     'ai_conf': ai_confidence,
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
                                             line_frame = crop_img.copy()
                                             self._draw_overlay_elements(line_frame, c_state, c_name)
                                             self.on_intruder_callback(c_name, line_frame, time.time())
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
                                                     line_frame = crop_img.copy()
                                                     self._draw_overlay_elements(line_frame, c_state, c_name)
                                                     self.on_intruder_callback(c_name, line_frame, time.time())
                                                 except Exception as e:
                                                     print(f"❌ Intruder callback error: {e}")
                                         else:
                                             c_state.last_intruder_msg = "Verifying Face..."
                                             c_state.last_intruder_color = (0, 165, 255)
                             except Exception as e:
                                 pass
                             finally:
                                 self._get_state(c_id).is_checking_face = False

                         threading.Thread(target=_async_face_check, args=(source_frame.copy(), camera_name, camera_id), daemon=True).start()
             else:
                 state.last_intruder_msg = ""
                 state.unknown_person_start_time = 0
                 state._intruder_callback_fired = False

             # Update fall counter
             # Decay slowly (every 2 consecutive no-fall frames) so brief occlusion
             # by other people doesn't fight against legitimate fall accumulation.
             if any_falling:
                 state.fall_counter += 1
                 state._no_fall_frames = 0
             else:
                 state._no_fall_frames += 1
                 if state._no_fall_frames >= 2:  # only decay after 2 consecutive no-fall frames
                     state.fall_counter = max(0, state.fall_counter - 1)
                     state._no_fall_frames = 0

             # Update state.persons_data first so it can be used for drawing clean LINE frames
             state.persons_data = persons_data

             if state.fall_counter >= self.fall_trigger_frames:
                state.status = '!!! FALL DETECTED !!!'
                state.color = (0, 0, 255) # Red
                self.async_play_alert(camera_name)
                if self.on_fall_callback and not state._fall_callback_fired:
                    state._fall_callback_fired = True
                    line_frame = source_frame.copy()
                    self._draw_overlay_elements(line_frame, state, camera_name)
                    ts_now = time.time()
                    cb = self.on_fall_callback

                    def _dispatch_fall(cb_fn=cb, cname=camera_name, img=line_frame, ts=ts_now):
                        try:
                            cb_fn(cname, img, ts)
                        except Exception as e:
                            print(f"❌ Fall callback error: {e}")

                    threading.Thread(target=_dispatch_fall, daemon=True).start()
             else:
                 state.status = 'Normal'
                 state.color = (0, 255, 0) # Green
                 state._fall_callback_fired = False

             # Backward compat
             self.fall_counter = state.fall_counter
             self.status = state.status
             self.color = state.color
             self._fall_callback_fired = state._fall_callback_fired

             if draw:
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
            if draw:
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
