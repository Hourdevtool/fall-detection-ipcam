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
import wave
import hashlib
import json
import urllib.parse
import urllib.request
import email.utils

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_AUDIO_CACHE_DIR = os.path.join(_PROJECT_ROOT, "Tools", "audio_cache")

from src.services.pose_features import (  # noqa: E402
    POSE_FEATURE_DIM,
    extract_pose_features,
    safe_torso_angle_and_dy,
)


def _ensure_siren_wav(filepath: str, mode: str = "fall") -> str:
    """Synthesize a crisp, urgent offline WAV alarm tone using numpy + wave (0 external deps)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
        return filepath

    sample_rate = 22050
    if mode == "fall":
        # Urgent medical 3-pulse alternating high-priority chime (880Hz / 1320Hz)
        tones = [(880.0, 0.14), (1320.0, 0.14), (880.0, 0.14), (1320.0, 0.18), (0.0, 0.06), (1320.0, 0.22)]
    else:
        # Security intruder rapid siren (950Hz / 1450Hz)
        tones = [(950.0, 0.12), (1450.0, 0.12), (950.0, 0.12), (1450.0, 0.12), (950.0, 0.18)]

    segments = []
    for freq, dur in tones:
        n_samples = int(sample_rate * dur)
        if freq <= 0:
            segments.append(np.zeros(n_samples, dtype=np.float32))
            continue
        t = np.linspace(0.0, dur, n_samples, endpoint=False, dtype=np.float32)
        # Fundamental + 2nd harmonic for clear speaker projection
        sig = 0.75 * np.sin(2.0 * np.pi * freq * t) + 0.25 * np.sin(2.0 * np.pi * (freq * 1.5) * t)
        # Smooth attack/release envelope to prevent speaker clicks
        fade = min(int(sample_rate * 0.012), n_samples // 4)
        if fade > 0:
            sig[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
            sig[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
        segments.append(sig)

    audio = np.concatenate(segments)
    pcm16 = np.clip(audio * 28000.0, -32767, 32767).astype(np.int16)

    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return filepath


class _CameraState:
    """Per-camera (or per-sub-frame) detection state."""
    def __init__(self):
        self.fall_counter = 0.0
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
        self.last_fall_confirmed_time = 0.0
        # Motion tracking for rapid drop detection
        self.prev_pose_time = 0.0
        self.prev_min_y1 = None
        self.prev_min_head_y = None
        self.prev_max_bh = None


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
    def __init__(self, yolo_path=None, rf_path=None, conf_threshold=0.42, fall_trigger_frames=3, on_fall_callback=None, on_intruder_callback=None):
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

        # Optimize PyTorch CPU threads (4 threads avoids oversubscription overhead on 8-thread CPUs)
        try:
            import torch
            torch.set_num_threads(4)
        except Exception:
            pass

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

        # Set PyTorch CPU threads AFTER loading sklearn/joblib so OpenMP doesn't reset thread pool
        try:
            import torch
            torch.set_num_threads(4)
        except Exception:
            pass

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
        self._audio_play_lock = threading.Lock()
        self._camera_states = {}

        self.fall_counter = 0.0
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

        # YOLO input size: 480 gives ~2.2x faster inference (~105ms vs ~230ms) with accurate pose keypoints
        self._yolo_input_size = 480

        # Warm up YOLO model once so the first live camera frame has zero JIT stall
        try:
            _dummy = np.zeros((288, 480, 3), dtype=np.uint8)
            self.pose_model(_dummy, imgsz=self._yolo_input_size, verbose=False, conf=self.conf_threshold)
        except Exception:
            pass

        # Initialize offline siren WAVs and Pygame Mixer
        os.makedirs(_AUDIO_CACHE_DIR, exist_ok=True)
        self._fall_siren_wav = _ensure_siren_wav(os.path.join(_AUDIO_CACHE_DIR, "siren_fall.wav"), mode="fall")
        self._intruder_siren_wav = _ensure_siren_wav(os.path.join(_AUDIO_CACHE_DIR, "siren_intruder.wav"), mode="intruder")
        self._fall_siren_sound = None
        self._intruder_siren_sound = None
        self._mixer_ready = False

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            self._mixer_ready = True
            self._fall_siren_sound = pygame.mixer.Sound(self._fall_siren_wav)
            self._intruder_siren_sound = pygame.mixer.Sound(self._intruder_siren_wav)
        except Exception as e:
            print(f"Failed to initialize pygame mixer: {e}")

        self.last_alert_time = 0.0
        self.last_intruder_alert_time = 0.0
        self.alert_cooldown = 8

        self.face_service = None
        self._face_service_loaded = False

        self.last_face_check_time = 0
        self.last_intruder_msg = ""
        self.last_intruder_color = (255, 255, 255)

        # Pre-warm Thai voice cache in background for known cameras so alerts play with 0ms network delay
        threading.Thread(target=self._prewarm_audio_cache, daemon=True, name="AudioPrewarm").start()

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

    def _classify_person_pose(self, prediction, ai_confidence, kpts_xyn, kpts_xy, kpts_conf, box_xywh, box_xyxyn, rapid_drop=False):
        """Decide (is_falling, label_text, geo, fall_weight) combining ML probabilities with strict sitting/occlusion guards."""
        pose_name = self.pose_labels.get(int(prediction), "Unknown")
        bw, bh = float(box_xywh[2]), float(box_xywh[3])
        y1, y2 = float(box_xyxyn[1]), float(box_xyxyn[3])
        bh_norm = max(0.0, y2 - y1)

        geo = self._analyze_skeleton_geometry(kpts_xy, bw, bh, box_xyxyn, kpts_conf=kpts_conf, min_conf=0.35)
        ar = geo['aspect_ratio']
        kpt_ar = geo['kpt_span_ratio']
        torso_angle = geo['torso_angle']
        dy_signed = geo['dy_signed']

        def _kp_ok(j, thr=0.35):
            return bool(kpts_conf[j] > thr and (kpts_xyn[j][0] > 0.01 or kpts_xyn[j][1] > 0.01))

        has_shoulders = any(_kp_ok(j, 0.40) for j in (5, 6))
        head_kpts_count = sum(1 for j in range(5) if _kp_ok(j, 0.35))
        has_upper_body = bool(has_shoulders or head_kpts_count >= 2)

        # Require higher confidence (0.48) for hips so desk/table occluded hip guesses (0.30-0.45) don't count as visible hips
        has_hips = any(_kp_ok(j, 0.48) for j in (11, 12))
        has_legs = any(_kp_ok(j, 0.38) for j in (13, 14, 15, 16))
        has_lower_body = bool(has_hips or has_legs)

        shoulders_y_norm = [float(kpts_xyn[j][1]) for j in (5, 6) if kpts_conf[j] > 0.40 and (kpts_xyn[j][0] > 0.01 or kpts_xyn[j][1] > 0.01)]
        hips_y_norm = [float(kpts_xyn[j][1]) for j in (11, 12) if kpts_conf[j] > 0.48 and (kpts_xyn[j][0] > 0.01 or kpts_xyn[j][1] > 0.01)]
        knees_y_norm = [float(kpts_xyn[j][1]) for j in (13, 14) if _kp_ok(j, 0.38)]
        ankles_y_norm = [float(kpts_xyn[j][1]) for j in (15, 16) if _kp_ok(j, 0.38)]

        sh_y_mean = float(np.mean(shoulders_y_norm)) if shoulders_y_norm else None
        hp_y_mean = float(np.mean(hips_y_norm)) if hips_y_norm else None
        kn_y_mean = float(np.mean(knees_y_norm)) if knees_y_norm else None
        ak_y_mean = float(np.mean(ankles_y_norm)) if ankles_y_norm else None

        # 1. Partial body / half-body crop ("เห็นคนครึ่งตัว"):
        # Must have visible shoulders + hips + legs. Also reject top-edge half-body crops (y1 < 0.08 and y2 < 0.52)
        # or headless crops (head_kpts_count == 0) that aren't clearly horizontal/inverted on the floor.
        if not (has_shoulders and has_hips and has_legs):
            return False, (pose_name if pose_name not in ("Fall", "Unknown") else "Sit"), geo, 0.0

        if (y1 < 0.08 and y2 < 0.52 and ar < 1.15):
            return False, (pose_name if pose_name not in ("Fall", "Unknown") else "Sit"), geo, 0.0

        # 2. Inverted torso on floor (head/shoulders physically lower on screen than hips, with legs above hips)
        legs_inverted_above_hips = bool(
            hp_y_mean is not None
            and kn_y_mean is not None and kn_y_mean < hp_y_mean - 0.05
            and (ak_y_mean is None or ak_y_mean < hp_y_mean - 0.05)
        )
        is_head_lower_than_hips = bool(
            sh_y_mean is not None and hp_y_mean is not None
            and (sh_y_mean > hp_y_mean + 0.06)
            and (legs_inverted_above_hips or ar > 1.05 or kpt_ar > 1.05)
        )

        # If head is completely unseen (cut off by frame edge) and body is neither inverted nor wide-horizontal, reject as half-body
        if head_kpts_count == 0 and not is_head_lower_than_hips and ar < 1.25 and kpt_ar < 1.25:
            return False, (pose_name if pose_name not in ("Fall", "Unknown") else "Sit"), geo, 0.0

        # 3. Upright / Sitting / Squatting / Leaning-Forward Guard ("เห็นท่าทางเอนก็บอกล้ม"):
        # If shoulders are above hips, feet/knees are below hips on the floor, and box/skeleton is taller than wide (ar < 1.06),
        # the person is sitting on a chair (even leaning forward 60+ deg!), squatting, or standing/bending — NEVER fallen on the floor.
        has_upright_vertical_chain = bool(
            sh_y_mean is not None and hp_y_mean is not None
            and sh_y_mean < hp_y_mean - 0.03
            and (
                (kn_y_mean is not None and kn_y_mean > hp_y_mean + 0.04)
                or (ak_y_mean is not None and ak_y_mean > hp_y_mean + 0.05)
            )
        )
        is_sitting_or_leaning_upright = bool(
            not is_head_lower_than_hips
            and not legs_inverted_above_hips
            and (
                # Normal upright sitting/standing
                ((torso_angle is not None and torso_angle < 48.0) and dy_signed > 0.0 and ar < 1.18)
                # Leaning forward on a chair or squatting: vertical top-to-bottom chain with taller-than-wide box
                or (has_upright_vertical_chain and ar < 1.06 and kpt_ar < 1.06)
            )
        )

        if is_sitting_or_leaning_upright:
            safe_label = pose_name if pose_name != "Fall" else ("Bend" if (torso_angle and torso_angle >= 45.0) else "Sit")
            return False, safe_label, geo, 0.0

        is_standing_bend = bool(
            prediction in (1, 3) and ai_confidence >= 0.45
            and has_legs and bh_norm >= 0.48 and ar < 1.08
            and (
                y1 <= 0.48
                or (sh_y_mean is not None and kn_y_mean is not None and hp_y_mean is not None and kn_y_mean > hp_y_mean + 0.04)
            )
        )

        # 4. Lying horizontally on the floor (requires wide horizontal posture, not an upright/narrow leaning box)
        is_lying_in_floor_zone = bool(
            not is_standing_bend
            and y1 > 0.25 and bh_norm < 0.65
            and (
                (ar > 1.25 and kpt_ar > 1.15 and (torso_angle is None or torso_angle > 45.0))
                or (torso_angle is not None and torso_angle > 58.0 and (ar > 1.08 or kpt_ar > 1.08))
            )
        )

        # 5. ML Fall prediction: MUST be supported by wide horizontal spread (ar > 1.10 / kpt_ar > 1.10) or inverted body
        ai_fall_allowed = bool(
            prediction == 4
            and (
                (ai_confidence >= 0.55 and (
                    (ar > 1.10 and kpt_ar > 1.08 and (torso_angle is None or torso_angle >= 42.0))
                    or legs_inverted_above_hips
                ))
                or (ai_confidence >= 0.85 and (ar > 1.12 or kpt_ar > 1.12))
            )
        )

        if is_head_lower_than_hips:
            return True, "FALL (Floor)", geo, 1.5
        if is_lying_in_floor_zone:
            weight = 1.5 if (ar > 1.35 or (torso_angle is not None and torso_angle > 62.0)) else 1.0
            return True, "FALL (Floor)", geo, weight
        if ai_fall_allowed:
            weight = 1.5 if (ai_confidence >= 0.78 or ar > 1.25 or (torso_angle is not None and torso_angle > 58.0)) else 1.0
            return True, f"FALL (AI {ai_confidence*100:.0f}%)", geo, weight
        if (
            not is_standing_bend
            and torso_angle is not None and torso_angle > 60.0
            and (ar > 1.10 or kpt_ar > 1.10)
            and y2 > 0.35 and bh_norm < 0.72
        ):
            return True, "FALL (Angle)", geo, 1.5

        return False, (pose_name if pose_name != "Fall" else "Sit"), geo, 0.0

    # ─── Multi-Layer Instant Audio Alert Engine (0ms Siren + Cached Thai TTS) ───

    def _tts_cache_path(self, text: str) -> str:
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
        return os.path.join(_AUDIO_CACHE_DIR, f"tts_{digest}.mp3")

    def _download_google_tts(self, text: str, dest_path: str, timeout: float = 2.5) -> bool:
        """Fast HTTP GET Thai TTS via Google Translate endpoint (no DRM token / no 403 clock issues)."""
        try:
            q = urllib.parse.quote(text)
            url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl=th&client=tw-ob&q={q}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                    "Referer": "https://translate.google.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if resp.status == 200 and len(data) > 512:
                    tmp_path = dest_path + ".tmp"
                    with open(tmp_path, "wb") as f:
                        f.write(data)
                    os.replace(tmp_path, dest_path)
                    return True
        except Exception:
            pass
        return False

    def _sync_edge_tts_clock_skew(self):
        """Sync edge_tts DRM clock skew from server HTTP Date header (handles PC clock set to 2026+)."""
        try:
            from edge_tts.drm import DRM
            req = urllib.request.Request("https://www.bing.com", method="HEAD")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                date_hdr = resp.headers.get("Date")
                if date_hdr:
                    srv_ts = email.utils.parsedate_to_datetime(date_hdr).timestamp()
                    now_ts = time.time()
                    DRM.clock_skew_seconds = srv_ts - now_ts
        except Exception:
            pass

    def _ensure_tts_file(self, text: str) -> str | None:
        """Return cached MP3 path for `text`, generating and caching it if missing."""
        os.makedirs(_AUDIO_CACHE_DIR, exist_ok=True)
        cache_path = self._tts_cache_path(text)
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 512:
            return cache_path

        # Tier 1: Google Translate Thai TTS (fast ~150-300ms HTTP GET, immune to Edge 403 DRM)
        if self._download_google_tts(text, cache_path, timeout=2.5):
            return cache_path

        # Tier 2: Edge TTS with HTTP Date clock-skew sync
        try:
            self._sync_edge_tts_clock_skew()
            tmp_path = cache_path + ".edge.tmp"

            async def _gen():
                communicate = edge_tts.Communicate(text, "th-TH-PremwadeeNeural")
                await communicate.save(tmp_path)

            asyncio.run(_gen())
            if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 512:
                os.replace(tmp_path, cache_path)
                return cache_path
        except Exception:
            pass

        return None

    def _prewarm_audio_cache(self):
        """Pre-generate Thai voice alerts for generic phrases and all saved cameras in background."""
        time.sleep(2.0)
        phrases = [
            "แจ้งเตือน ตรวจพบการล้ม",
            "แจ้งเตือน พบผู้บุกรุก",
        ]
        try:
            cam_cfg = os.path.join(_PROJECT_ROOT, "config", "cameras.json")
            if os.path.exists(cam_cfg):
                with open(cam_cfg, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for val in data.values():
                        cname = val.get("name") if isinstance(val, dict) else str(val)
                        if cname:
                            phrases.append(f"แจ้งเตือน ตรวจพบการล้มที่ {cname}")
                            phrases.append(f"แจ้งเตือน พบผู้บุกรุกที่ {cname}")
        except Exception:
            pass

        for text in phrases:
            try:
                res = self._ensure_tts_file(text)
                if res is None:
                    # Network unreachable — stop pre-warming so we don't waste background sockets
                    break
            except Exception:
                break

    def _play_instant_siren(self, mode: str = "fall"):
        """Fire offline emergency siren in <5ms (zero network dependency)."""
        played = False
        if self._mixer_ready:
            try:
                snd = self._fall_siren_sound if mode == "fall" else self._intruder_siren_sound
                if snd is not None:
                    snd.play()
                    played = True
            except Exception:
                pass

        if not played:
            try:
                import winsound
                winsound.Beep(1200 if mode == "fall" else 1400, 220)
                winsound.Beep(880 if mode == "fall" else 950, 220)
            except Exception:
                pass

    def _play_voice_alert(self, primary_text: str, fallback_text: str, mode: str = "fall"):
        """Play instant siren immediately, followed by cached/synthesized Thai voice alert."""
        # Step 1: Immediate 0ms siren sound on speaker
        self._play_instant_siren(mode=mode)

        # Step 2: Resolve cached or synthesized Thai voice MP3
        def _worker():
            mp3_path = self._ensure_tts_file(primary_text)
            if not mp3_path:
                mp3_path = self._ensure_tts_file(fallback_text)

            with self._audio_play_lock:
                # Brief pause so initial siren chime finishes cleanly before voice speaks
                time.sleep(0.55)
                if mp3_path and self._mixer_ready and os.path.exists(mp3_path):
                    try:
                        pygame.mixer.music.load(mp3_path)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy():
                            time.sleep(0.05)
                        pygame.mixer.music.unload()
                        return
                    except Exception as e:
                        print(f"⚠️ Voice playback fallback ({e})")

                # Offline fallback if no MP3 could be generated/loaded: repeat emergency siren
                self._play_instant_siren(mode=mode)

        threading.Thread(target=_worker, daemon=True).start()

    def async_play_alert(self, camera_name):
        current_time = time.time()
        if current_time - self.last_alert_time < self.alert_cooldown:
            return
        self.last_alert_time = current_time
        self._play_voice_alert(
            primary_text=f"แจ้งเตือน ตรวจพบการล้มที่ {camera_name}",
            fallback_text="แจ้งเตือน ตรวจพบการล้ม",
            mode="fall",
        )

    def async_play_intruder_alert(self, camera_name):
        current_time = time.time()
        if current_time - self.last_intruder_alert_time < self.alert_cooldown:
            return
        self.last_intruder_alert_time = current_time
        self._play_voice_alert(
            primary_text=f"แจ้งเตือน พบผู้บุกรุกที่ {camera_name}",
            fallback_text="แจ้งเตือน พบผู้บุกรุก",
            mode="intruder",
        )

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
                imgsz=self._yolo_input_size,
                verbose=False,
                conf=self.conf_threshold,
            )

        now_ts = time.time()

        if results[0].keypoints is not None and len(results[0].keypoints) > 0:
             if draw:
                 annotated = results[0].plot()
                 frame = cv2.resize(annotated, (w, h), interpolation=cv2.INTER_LINEAR) if infer_frame is not frame else annotated

             num_persons = len(results[0].keypoints)
             any_falling = False
             max_fall_weight = 0.0
             persons_data = []

             all_kpts_xyn = results[0].keypoints.xyn.cpu().numpy()
             all_kpts_xy = results[0].keypoints.xy.cpu().numpy()
             if results[0].keypoints.conf is not None:
                 all_kpts_conf = results[0].keypoints.conf.cpu().numpy()
             else:
                 all_kpts_conf = np.ones((num_persons, 17), dtype=np.float32)

             all_boxes_xywh = results[0].boxes.xywh.cpu().numpy()
             all_boxes_xyxyn = results[0].boxes.xyxyn.cpu().numpy()

             # Check rapid vertical drop across frames (< 0.85s window)
             cur_min_y1 = float(np.min(all_boxes_xyxyn[:, 1]))
             cur_max_bh = float(np.max(all_boxes_xyxyn[:, 3] - all_boxes_xyxyn[:, 1]))
             rapid_drop_detected = False
             dt = now_ts - state.prev_pose_time if state.prev_pose_time > 0 else 999.0
             if 0.02 <= dt <= 0.85 and state.prev_min_y1 is not None and state.prev_max_bh is not None:
                 dy1 = cur_min_y1 - state.prev_min_y1
                 dbh = state.prev_max_bh - cur_max_bh
                 # Rapid downward shift of top of person box or rapid height collapse
                 if dy1 >= 0.11 or (dy1 >= 0.07 and dbh >= 0.10):
                     rapid_drop_detected = True

             state.prev_pose_time = now_ts
             state.prev_min_y1 = cur_min_y1
             state.prev_max_bh = cur_max_bh

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

                 is_falling, label_text, _geo, fall_weight = self._classify_person_pose(
                     prediction, ai_confidence, kpts, kpts_xy, kpts_conf, box, box_xyxyn,
                     rapid_drop=rapid_drop_detected,
                 )

                 if is_falling:
                     any_falling = True
                     if fall_weight > max_fall_weight:
                         max_fall_weight = fall_weight

                 persons_data.append({
                     'kpts_xyn': kpts,
                     'box_xyxyn': box_xyxyn,
                     'pose_name': "Fall" if is_falling else label_text,
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

             # Update weighted fall counter:
             # High-certainty falls add up to +2.0 so clear falls trigger immediately!
             if any_falling:
                 state.fall_counter = min(float(self.fall_trigger_frames) + 2.0, state.fall_counter + max(1.0, max_fall_weight))
                 state._no_fall_frames = 0
             else:
                 state._no_fall_frames += 1
                 if state._no_fall_frames >= 2:  # only decay after 2 consecutive no-fall frames
                     state.fall_counter = max(0.0, state.fall_counter - 1.0)
                     state._no_fall_frames = 0

             # Update state.persons_data first so it can be used for drawing clean LINE frames
             state.persons_data = persons_data

             is_triggered = (
                 state.fall_counter >= self.fall_trigger_frames
                 or (state.last_fall_confirmed_time > 0 and (now_ts - state.last_fall_confirmed_time) < 1.5 and any_falling)
             )

             if is_triggered:
                if state.fall_counter >= self.fall_trigger_frames:
                    state.last_fall_confirmed_time = now_ts
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
             elif state.last_fall_confirmed_time > 0 and (now_ts - state.last_fall_confirmed_time) < 1.2:
                 # Keep red alert banner steady for 1.2s so brief keypoint flicker doesn't blink UI
                 state.status = '!!! FALL DETECTED !!!'
                 state.color = (0, 0, 255)
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
            state.fall_counter = 0.0
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
