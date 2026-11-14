"""
Shared pose feature extraction & skeleton geometry helpers.

Provides a single source of truth used by dataset preparation (`Tools/prepare_dataset.py`),
model training (`Tools/train_multipose.py`), and live inference (`detection.py`).

All features are position-, scale-, and occlusion-invariant so that:
- A sitting person with legs/hips hidden behind a table is NOT confused with a fall.
- Both pixel coordinates (`keypoints.xy`) and uniform 1:1 coordinates produce true
  geometric torso/thigh angles without 16:9 aspect-ratio distortion.
"""

import numpy as np


POSE_FEATURE_DIM = 63

KEYPOINT_NAMES = [
    "Nose", "Left Eye", "Right Eye", "Left Ear", "Right Ear",
    "Left Shoulder", "Right Shoulder", "Left Elbow", "Right Elbow",
    "Left Wrist", "Right Wrist", "Left Hip", "Right Hip",
    "Left Knee", "Right Knee", "Left Ankle", "Right Ankle",
]


def safe_torso_angle_and_dy(kpts_xy, valid):
    """Compute true torso angle (0=vertical, 90=horizontal) and signed dy (hip_y - shoulder_y).

    Uses matched same-side pairs when only one hip or one shoulder is visible
    to avoid diagonal tilt artifacts when the opposite side is occluded.

    Returns:
        (angle_deg, dy_signed, torso_len): angle_deg is None if torso cannot be measured.
    """
    kpts = np.asarray(kpts_xy, dtype=np.float32)
    l_sh = bool(valid[5])
    r_sh = bool(valid[6])
    l_hp = bool(valid[11])
    r_hp = bool(valid[12])

    pairs = []
    if l_sh and l_hp and r_sh and r_hp:
        s_xy = (kpts[5] + kpts[6]) * 0.5
        h_xy = (kpts[11] + kpts[12]) * 0.5
        pairs.append((s_xy, h_xy))
    else:
        if l_sh and l_hp:
            pairs.append((kpts[5], kpts[11]))
        if r_sh and r_hp:
            pairs.append((kpts[6], kpts[12]))
        if not pairs and (l_sh or r_sh) and (l_hp or r_hp):
            shs = [kpts[j] for j in (5, 6) if valid[j]]
            hps = [kpts[j] for j in (11, 12) if valid[j]]
            pairs.append((np.mean(shs, axis=0), np.mean(hps, axis=0)))

    if not pairs:
        return None, 0.0, 0.0

    s_xy = np.mean([p[0] for p in pairs], axis=0)
    h_xy = np.mean([p[1] for p in pairs], axis=0)
    dx = abs(float(s_xy[0] - h_xy[0]))
    dy_signed = float(h_xy[1] - s_xy[1])  # >0 means shoulders are higher (smaller y) than hips
    ang = float(np.degrees(np.arctan2(dx, abs(dy_signed) + 1e-6)))
    torso_len = float(np.hypot(dx, dy_signed))
    return ang, dy_signed, torso_len


def extract_pose_features(kpts_xy, conf=None, min_conf=0.30):
    """Extract 63 position-, scale-, and occlusion-invariant features from (17, 2) keypoints.

    Features [0..50]: Per-keypoint bounding-box-normalized (nx, ny, visible_flag) x 17.
    Features [51..62]: 12 biomechanical ratios & flags (aspect ratio, torso angle,
        signed torso dy, head->hip dy, head->shoulder dy, shoulder width,
        hip->knee dy, knee->ankle dy, thigh angle, has_hips, has_knees, has_ankles).
    """
    kpts = np.asarray(kpts_xy, dtype=np.float32)
    if kpts.shape != (17, 2):
        kpts = kpts.reshape(17, 2)

    nonzero = (np.abs(kpts[:, 0]) > 1e-4) | (np.abs(kpts[:, 1]) > 1e-4)
    if conf is None:
        valid = nonzero
    else:
        conf_arr = np.asarray(conf, dtype=np.float32)
        valid = (conf_arr >= min_conf) & nonzero

    feats = np.zeros(POSE_FEATURE_DIM, dtype=np.float32)
    if int(valid.sum()) < 2:
        return feats

    xs = kpts[valid, 0]
    ys = kpts[valid, 1]
    min_x, max_x = float(xs.min()), float(xs.max())
    min_y, max_y = float(ys.min()), float(ys.max())
    w = max_x - min_x
    h = max_y - min_y
    scale = max(w, h, 1e-4)
    cx = (min_x + max_x) * 0.5
    cy = (min_y + max_y) * 0.5

    for j in range(17):
        if valid[j]:
            feats[j * 3] = (kpts[j, 0] - cx) / scale
            feats[j * 3 + 1] = (kpts[j, 1] - cy) / scale
            feats[j * 3 + 2] = 1.0

    ar_kpts = min(w / max(h, 1e-4), 5.0)
    ang, dy_torso, _ = safe_torso_angle_and_dy(kpts, valid)
    ang_norm = (ang / 90.0) if ang is not None else 0.5
    dy_torso_norm = dy_torso / scale

    head_ys = [kpts[j, 1] for j in range(5) if valid[j]]
    sh_ys = [kpts[j, 1] for j in (5, 6) if valid[j]]
    hp_ys = [kpts[j, 1] for j in (11, 12) if valid[j]]
    kn_ys = [kpts[j, 1] for j in (13, 14) if valid[j]]
    ak_ys = [kpts[j, 1] for j in (15, 16) if valid[j]]

    head_y = float(np.mean(head_ys)) if head_ys else (float(np.mean(sh_ys)) if sh_ys else cy)
    sh_y = float(np.mean(sh_ys)) if sh_ys else head_y
    hp_y = float(np.mean(hp_ys)) if hp_ys else None
    kn_y = float(np.mean(kn_ys)) if kn_ys else None
    ak_y = float(np.mean(ak_ys)) if ak_ys else None

    head_to_sh_dy = (sh_y - head_y) / scale
    head_to_hp_dy = ((hp_y - head_y) / scale) if hp_y is not None else 0.0
    sh_width = (abs(float(kpts[5, 0] - kpts[6, 0])) / scale) if (valid[5] and valid[6]) else 0.0
    hp_to_kn_dy = ((kn_y - hp_y) / scale) if (hp_y is not None and kn_y is not None) else 0.0
    kn_to_ak_dy = ((ak_y - kn_y) / scale) if (kn_y is not None and ak_y is not None) else 0.0

    # Thigh angle (hip -> knee): sitting ~ horizontal (~1.0), standing ~ vertical (~0.0)
    thigh_ang = 0.0
    if (valid[11] and valid[13]) or (valid[12] and valid[14]):
        t_angs = []
        if valid[11] and valid[13]:
            dx = abs(float(kpts[13, 0] - kpts[11, 0]))
            dy = abs(float(kpts[13, 1] - kpts[11, 1]))
            t_angs.append(np.degrees(np.arctan2(dx, dy + 1e-6)) / 90.0)
        if valid[12] and valid[14]:
            dx = abs(float(kpts[14, 0] - kpts[12, 0]))
            dy = abs(float(kpts[14, 1] - kpts[12, 1]))
            t_angs.append(np.degrees(np.arctan2(dx, dy + 1e-6)) / 90.0)
        thigh_ang = float(np.mean(t_angs))

    has_hips = 1.0 if hp_ys else 0.0
    has_knees = 1.0 if kn_ys else 0.0
    has_ankles = 1.0 if ak_ys else 0.0

    feats[51:63] = [
        ar_kpts, ang_norm, dy_torso_norm, head_to_hp_dy, head_to_sh_dy,
        sh_width, hp_to_kn_dy, kn_to_ak_dy, thigh_ang,
        has_hips, has_knees, has_ankles,
    ]
    return feats
