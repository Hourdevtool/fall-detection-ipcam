r"""
prepare_dataset.py -- Convert all dataset formats (CSV / JPG / AVI)
into a clean, pose-invariant multipose_dataset.csv ready for training.

5 Classes (no "resting"):
  0 = walk     (เดิน)
  1 = stand    (ยืน)
  2 = sit      (นั่ง)
  3 = bend     (ก้มเก็บของ)
  4 = fall     (ล้ม)

Key improvements over legacy 34-feature extractor:
  1. Uses 63 scale-, position-, and occlusion-invariant biomechanical features
     from src.services.pose_features (pixel/uniform coordinates, not raw frame coords).
  2. Filters Fall/{Bed,Chair,Stand} CSV sequences to exclude pre-fall upright frames.
  3. Filters No Fall/Chair CSV sequences to seated frames.
  4. Adds horizontal-flip & realistic lower-body/table-occlusion augmentations
     (ankles/knees/hips/single-side masked) so sitting behind a desk is never
     misclassified as a fall.
  5. Records `group` IDs per source file so train/test split avoids data leakage.

Usage:
  python Tools/prepare_dataset.py
"""

import csv
import glob
import json
import os
import random
import sys

import cv2
import numpy as np

# Force unbuffered output so logs appear in real-time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TOOLS_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.pose_features import (  # noqa: E402
    KEYPOINT_NAMES,
    POSE_FEATURE_DIM,
    extract_pose_features,
    safe_torso_angle_and_dy,
)

DATASET_DIR = os.path.join(TOOLS_DIR, "dataset")
OUTPUT_CSV = os.path.join(TOOLS_DIR, "multipose_dataset.csv")
LABELS_JSON = os.path.join(TOOLS_DIR, "pose_labels.json")

KP_IDX = {name: i for i, name in enumerate(KEYPOINT_NAMES)}

LABEL_MAP = {
    "walk": 0,
    "stand": 1,
    "sit": 2,
    "bend": 3,
    "fall": 4,
}
LABEL_NAMES = {v: k for k, v in LABEL_MAP.items()}

MAX_FRAMES_PER_CSV = 10
MAX_FRAMES_PER_VIDEO = 8
MAX_WALK_VIDEOS = 250
YOLO_IMG_SIZE = 480

random.seed(42)
np.random.seed(42)


def parse_vertical_csv_sequence(csv_path, min_valid_kpts=10):
    """Parse a (Frame, Keypoint, X, Y, Confidence) CSV into ordered [(fn, kpts, conf), ...]."""
    frames = {}
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    fn = int(row["Frame"])
                    idx = KP_IDX.get(row["Keypoint"].strip())
                    if idx is None:
                        continue
                    x = float(row["X"])
                    y = float(row["Y"])
                    c = float(row["Confidence"])
                    if fn not in frames:
                        frames[fn] = [
                            np.zeros((17, 2), dtype=np.float32),
                            np.zeros(17, dtype=np.float32),
                        ]
                    if c > frames[fn][1][idx]:
                        frames[fn][0][idx] = [x, y]
                        frames[fn][1][idx] = c
                except (ValueError, KeyError):
                    continue
    except Exception as e:
        print(f"  ⚠️ Error reading {csv_path}: {e}")
        return []

    out = []
    for fn in sorted(frames.keys()):
        kpts, conf = frames[fn]
        if int((conf > 0.30).sum()) >= min_valid_kpts:
            out.append((fn, kpts, conf))
    return out


def hflip_kpts(kpts, conf):
    """Horizontally mirror keypoints and swap left/right anatomical indices."""
    k = kpts.copy()
    c = conf.copy()
    max_x = float(k[:, 0].max()) + 10.0
    k[:, 0] = max_x - k[:, 0]
    for a, b in [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16)]:
        k[[a, b]] = k[[b, a]]
        c[[a, b]] = c[[b, a]]
    return k, c


def augment_occlusion(kpts, conf, mode):
    """Mask out subsets of keypoints to simulate furniture/table/side occlusion."""
    k = kpts.copy()
    c = conf.copy()
    mask_map = {
        "ankles": [15, 16],
        "knees_ankles": [13, 14, 15, 16],
        "hips_down": [11, 12, 13, 14, 15, 16],
        "left_leg": [11, 13, 15],
        "right_leg": [12, 14, 16],
    }
    idxs = mask_map[mode]
    c[idxs] = 0.0
    k[idxs] = 0.0
    return k, c


def build_group_rows(sample_pairs, cls_id, group_id, rng):
    """Convert [(kpts, conf), ...] from a single clip/image into feature rows with augmentations."""
    rows = []
    for kpts, conf in sample_pairs:
        # Clean
        rows.append(extract_pose_features(kpts, conf).tolist() + [group_id, cls_id])
        # Horizontal mirror
        kf, cf = hflip_kpts(kpts, conf)
        rows.append(extract_pose_features(kf, cf).tolist() + [group_id, cls_id])

        if cls_id in (0, 1, 2, 3):
            # All non-fall poses get realistic partial/lower-body occlusion augmentation
            mode1 = rng.choice(["ankles", "knees_ankles", "hips_down", "left_leg", "right_leg"])
            ko, co = augment_occlusion(kpts, conf, mode1)
            rows.append(extract_pose_features(ko, co).tolist() + [group_id, cls_id])

            if cls_id == 2:
                # Extra table-occlusion examples for sitting (knees+ankles & hips+down)
                for sit_mode in ("knees_ankles", "hips_down"):
                    ko2, co2 = augment_occlusion(kpts, conf, sit_mode)
                    rows.append(extract_pose_features(ko2, co2).tolist() + [group_id, cls_id])
                    ko2f, co2f = augment_occlusion(kf, cf, sit_mode)
                    rows.append(extract_pose_features(ko2f, co2f).tolist() + [group_id, cls_id])
        elif cls_id == 4:
            # Falls can also have one side or ankles occluded while staying fallen
            mode_f = rng.choice(["ankles", "left_leg", "right_leg"])
            ko, co = augment_occlusion(kpts, conf, mode_f)
            rows.append(extract_pose_features(ko, co).tolist() + [group_id, cls_id])
    return rows


def collect_fall_csvs(base_dir, rng):
    """Collect ONLY truly fallen/falling frames from Fall/{Bed,Chair,Stand} CSV sequences."""
    csv_files = sorted(glob.glob(os.path.join(base_dir, "**", "*.csv"), recursive=True))
    print(f"  พบ {len(csv_files)} CSV files")
    all_rows = []
    for i, csv_path in enumerate(csv_files):
        seq = parse_vertical_csv_sequence(csv_path)
        if not seq:
            continue
        init_hs = [
            seq[j][1][seq[j][2] > 0.30, 1].max() - seq[j][1][seq[j][2] > 0.30, 1].min()
            for j in range(min(3, len(seq)))
            if (seq[j][2] > 0.30).any()
        ]
        base_h = float(np.median(init_hs)) if init_hs else 200.0
        fallen = []
        for idx, (_fn, kpts, conf) in enumerate(seq):
            valid = conf > 0.30
            xs, ys = kpts[valid, 0], kpts[valid, 1]
            w = float(xs.max() - xs.min())
            h = float(ys.max() - ys.min())
            ar = w / max(h, 1e-4)
            ang, dy_signed, _ = safe_torso_angle_and_dy(kpts, valid)
            if ang is None:
                continue
            if (
                ang > 50.0
                or ar > 1.25
                or dy_signed <= 0.05 * max(base_h, 1.0)
                or (h < 0.55 * base_h and idx >= len(seq) // 3)
            ):
                fallen.append((kpts, conf))
        if fallen:
            chosen = rng.sample(fallen, min(MAX_FRAMES_PER_CSV, len(fallen)))
            gid = f"csv_fall_{os.path.relpath(csv_path, DATASET_DIR)}"
            all_rows.extend(build_group_rows(chosen, 4, gid, rng))
        if (i + 1) % 200 == 0:
            print(f"    Processed {i+1}/{len(csv_files)} CSVs, {len(all_rows)} samples so far")
    print(f"  ✅ ได้ {len(all_rows)} samples (clean fallen frames + aug)")
    return all_rows


def collect_nofall_csvs(base_dir, cls_id, rng, skip_initial_fraction=0.0):
    """Collect upright Stand or seated Chair samples from No Fall CSV sequences."""
    csv_files = sorted(glob.glob(os.path.join(base_dir, "**", "*.csv"), recursive=True))
    print(f"  พบ {len(csv_files)} CSV files")
    all_rows = []
    for i, csv_path in enumerate(csv_files):
        seq = parse_vertical_csv_sequence(csv_path)
        if not seq:
            continue
        start_idx = int(len(seq) * skip_initial_fraction)
        subset = seq[start_idx:] or seq
        chosen_seq = rng.sample(subset, min(MAX_FRAMES_PER_CSV, len(subset)))
        pairs = [(k, c) for _, k, c in chosen_seq]
        gid = f"csv_{cls_id}_{os.path.relpath(csv_path, DATASET_DIR)}"
        all_rows.extend(build_group_rows(pairs, cls_id, gid, rng))
        if (i + 1) % 200 == 0:
            print(f"    Processed {i+1}/{len(csv_files)} CSVs, {len(all_rows)} samples so far")
    print(f"  ✅ ได้ {len(all_rows)} samples")
    return all_rows


def collect_archive_images(folder_dir, cls_id, yolo_model, rng, prefix):
    """Extract keypoints from image folders using YOLOv8-Pose in pixel space."""
    exts = (".jpg", ".jpeg", ".png", ".bmp")
    img_files = sorted(
        f for f in os.listdir(folder_dir) if f.lower().endswith(exts)
    )
    print(f"  พบ {len(img_files)} รูปภาพ")
    all_rows = []
    for i, fname in enumerate(img_files):
        fpath = os.path.join(folder_dir, fname)
        img = cv2.imread(fpath)
        if img is None:
            continue
        results = yolo_model(img, verbose=False, conf=0.35, imgsz=YOLO_IMG_SIZE)
        if results[0].keypoints is not None and len(results[0].keypoints) > 0:
            kpts = results[0].keypoints.xy[0].cpu().numpy()
            conf = results[0].keypoints.conf[0].cpu().numpy()
            if int((conf > 0.30).sum()) >= 5:
                gid = f"img_{prefix}_{fname}"
                all_rows.extend(build_group_rows([(kpts, conf)], cls_id, gid, rng))
        if (i + 1) % 300 == 0:
            print(f"    Processed {i+1}/{len(img_files)} images, {len(all_rows)} samples so far")
    return all_rows


def collect_archive_videos(folder_dir, cls_id, yolo_model, rng, prefix, max_videos=None):
    """Extract sampled frames from AVI/MP4 folders using YOLOv8-Pose in pixel space."""
    exts = (".avi", ".mp4", ".mov", ".mkv")
    vid_files = sorted(
        f for f in os.listdir(folder_dir) if f.lower().endswith(exts)
    )
    if max_videos and len(vid_files) > max_videos:
        rng.shuffle(vid_files)
        vid_files = vid_files[:max_videos]
    print(f"  พบ/ใช้ {len(vid_files)} วิดีโอ")
    all_rows = []
    for i, fname in enumerate(vid_files):
        fpath = os.path.join(folder_dir, fname)
        cap = cv2.VideoCapture(fpath)
        if not cap.isOpened():
            continue
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            continue
        indices = (
            sorted(rng.sample(range(total), MAX_FRAMES_PER_VIDEO))
            if total > MAX_FRAMES_PER_VIDEO
            else list(range(total))
        )
        pairs = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            results = yolo_model(frame, verbose=False, conf=0.35, imgsz=YOLO_IMG_SIZE)
            if results[0].keypoints is not None and len(results[0].keypoints) > 0:
                kpts = results[0].keypoints.xy[0].cpu().numpy()
                conf = results[0].keypoints.conf[0].cpu().numpy()
                if int((conf > 0.30).sum()) >= 6:
                    pairs.append((kpts, conf))
        cap.release()
        if pairs:
            gid = f"vid_{prefix}_{fname}"
            all_rows.extend(build_group_rows(pairs, cls_id, gid, rng))
        if (i + 1) % 50 == 0:
            print(f"    Processed {i+1}/{len(vid_files)} videos, {len(all_rows)} samples so far")
    return all_rows


def main():
    rng = random.Random(42)
    print("=" * 60)
    print("  🔄 PREPARE MULTI-POSE DATASET (63 Pose-Invariant Features)")
    print("  5 Classes: walk(0) / stand(1) / sit(2) / bend(3) / fall(4)")
    print("=" * 60)
    print()

    class_data = {0: [], 1: [], 2: [], 3: [], 4: []}

    # 1. CSV datasets
    for subfolder in ["Bed", "Chair", "Stand"]:
        path = os.path.join(DATASET_DIR, "Fall", subfolder)
        if os.path.exists(path):
            print(f"\n🔴 Fall/{subfolder} → class 4 (fall, cleaned)")
            class_data[4].extend(collect_fall_csvs(path, rng))

    nf_stand = os.path.join(DATASET_DIR, "No Fall", "Stand")
    if os.path.exists(nf_stand):
        print("\n🟢 No Fall/Stand → class 1 (stand)")
        class_data[1].extend(collect_nofall_csvs(nf_stand, 1, rng))

    nf_chair = os.path.join(DATASET_DIR, "No Fall", "Chair")
    if os.path.exists(nf_chair):
        print("\n🟢 No Fall/Chair → class 2 (sit)")
        class_data[2].extend(collect_nofall_csvs(nf_chair, 2, rng, skip_initial_fraction=0.35))

    # 2. Archive JPG + AVI datasets
    archive_sources = {
        "walk": (0, "video", MAX_WALK_VIDEOS),
        "standing": (1, "image", None),
        "sitting": (2, "image", None),
        "sit": (2, "video", None),
        "bending": (3, "image", None),
    }

    has_media = any(
        os.path.exists(os.path.join(DATASET_DIR, "archive", folder))
        for folder in archive_sources
    )
    yolo_model = None
    if has_media:
        print("\n🤖 Loading YOLOv8 Pose model...")
        from ultralytics import YOLO  # type: ignore

        yolo_path = os.path.join(TOOLS_DIR, "yolov8n-pose.pt")
        yolo_model = YOLO(yolo_path)
        print("  ✅ YOLO loaded")

    if yolo_model:
        for folder, (cls_id, ftype, cap_vids) in archive_sources.items():
            path = os.path.join(DATASET_DIR, "archive", folder)
            if not os.path.exists(path) and folder == "sit":
                alt_path = os.path.join(TOOLS_DIR, "sit")
                if os.path.exists(alt_path):
                    path = alt_path
            if not os.path.exists(path):
                continue
            print(f"\n🟡 archive/{folder} ({ftype}) → class {cls_id} ({LABEL_NAMES[cls_id]})")
            if ftype == "image":
                rows = collect_archive_images(path, cls_id, yolo_model, rng, folder)
            else:
                rows = collect_archive_videos(path, cls_id, yolo_model, rng, folder, max_videos=cap_vids)
            class_data[cls_id].extend(rows)
            print(f"  ✅ ได้ {len(rows)} samples")

    print("\n" + "━" * 50)
    print("📊 สรุปจำนวน samples ทั้งหมด (พร้อม group IDs + occlusion aug):")
    all_rows = []
    for cls_id in range(5):
        cnt = len(class_data[cls_id])
        print(f"  Class {cls_id} ({LABEL_NAMES[cls_id]:>6}): {cnt:>8} samples")
        all_rows.extend(class_data[cls_id])

    rng.shuffle(all_rows)
    header = [f"f{i}" for i in range(POSE_FEATURE_DIM)] + ["group", "class"]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(all_rows)

    print(f"\n💾 Saved {len(all_rows)} rows ({POSE_FEATURE_DIM} features) -> {OUTPUT_CSV}")

    labels_info = {
        "labels": LABEL_MAP,
        "names": {str(k): v for k, v in LABEL_NAMES.items()},
        "n_features": POSE_FEATURE_DIM,
        "total_samples": len(all_rows),
        "samples_per_class": {LABEL_NAMES[k]: len(class_data[k]) for k in range(5)},
    }
    with open(LABELS_JSON, "w", encoding="utf-8") as f:
        json.dump(labels_info, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved metadata -> {LABELS_JSON}")


if __name__ == "__main__":
    main()
