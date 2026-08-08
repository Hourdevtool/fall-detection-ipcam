r"""
prepare_dataset.py -- Convert all dataset formats (CSV / JPG / AVI)
into a single multipose_dataset.csv ready for training.

5 Classes (no "resting"):
  0 = walk     (เดิน)
  1 = stand    (ยืน)
  2 = sit      (นั่ง)
  3 = bend     (ก้มเก็บของ)
  4 = fall     (ล้ม)

Usage:
  cd d:\buff_p\Tools
  python prepare_dataset.py
"""

import os
import sys
import csv
import json
import random
import numpy as np

# Force unbuffered output so logs appear in real-time
sys.stdout.reconfigure(line_buffering=True)

# ────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────
DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset")
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "multipose_dataset.csv")
LABELS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pose_labels.json")

# YOLOv8 Pose keypoint names ตามลำดับ
KEYPOINT_NAMES = [
    "Nose", "Left Eye", "Right Eye", "Left Ear", "Right Ear",
    "Left Shoulder", "Right Shoulder", "Left Elbow", "Right Elbow",
    "Left Wrist", "Right Wrist", "Left Hip", "Right Hip",
    "Left Knee", "Right Knee", "Left Ankle", "Right Ankle"
]

LABEL_MAP = {
    "walk": 0,
    "stand": 1,
    "sit": 2,
    "bend": 3,
    "fall": 4,
}

LABEL_NAMES = {v: k for k, v in LABEL_MAP.items()}

# จำนวน frames ที่จะสุ่มจากแต่ละ CSV (เพื่อลดข้อมูลที่เยอะเกิน)
MAX_FRAMES_PER_CSV = 15

# จำนวน frames ที่จะสุ่มจากแต่ละ video
MAX_FRAMES_PER_VIDEO = 20

# Target samples per class สำหรับ balancing
TARGET_SAMPLES_PER_CLASS = None  # จะคำนวณอัตโนมัติจาก class ที่น้อยที่สุด

random.seed(42)
np.random.seed(42)


# ────────────────────────────────────────────
# PART 1: แปลง CSV (แนวตั้ง) → rows (แนวนอน normalized)
# ────────────────────────────────────────────
def parse_vertical_csv(csv_path, max_frames=MAX_FRAMES_PER_CSV):
    """
    อ่าน CSV แนวตั้ง (Frame,Keypoint,X,Y,Confidence)
    แปลงเป็น list ของ rows [x0,y0,x1,y1,...,x16,y16]
    Normalize ค่า x,y ให้เป็น 0-1
    """
    frames_data = {}  # {frame_num: {keypoint_name: (x, y, conf)}}

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    frame_num = int(row["Frame"])
                    kp_name = row["Keypoint"].strip()
                    x = float(row["X"])
                    y = float(row["Y"])
                    conf = float(row["Confidence"])
                    
                    if frame_num not in frames_data:
                        frames_data[frame_num] = {}
                    frames_data[frame_num][kp_name] = (x, y, conf)
                except (ValueError, KeyError):
                    continue
    except Exception as e:
        print(f"  ⚠️ Error reading {csv_path}: {e}")
        return []

    if not frames_data:
        return []

    # สุ่มเลือก frames
    all_frame_nums = sorted(frames_data.keys())
    if len(all_frame_nums) > max_frames:
        selected_frames = sorted(random.sample(all_frame_nums, max_frames))
    else:
        selected_frames = all_frame_nums

    rows = []
    for frame_num in selected_frames:
        kps = frames_data[frame_num]
        
        # ต้องมี keypoints ครบ 17 จุด
        if len(kps) < 17:
            continue

        # หาค่า max x, y สำหรับ normalize
        all_x = [kps[name][0] for name in KEYPOINT_NAMES if name in kps]
        all_y = [kps[name][1] for name in KEYPOINT_NAMES if name in kps]
        
        if not all_x or not all_y:
            continue
            
        max_x = max(all_x) if max(all_x) > 0 else 1.0
        max_y = max(all_y) if max(all_y) > 0 else 1.0

        # สร้าง row แนวนอน [x0,y0,x1,y1,...,x16,y16]
        row = []
        valid = True
        for kp_name in KEYPOINT_NAMES:
            if kp_name in kps:
                x_norm = kps[kp_name][0] / max_x
                y_norm = kps[kp_name][1] / max_y
                row.extend([x_norm, y_norm])
            else:
                valid = False
                break

        if valid and len(row) == 34:
            rows.append(row)

    return rows


# ────────────────────────────────────────────
# PART 2: แปลง JPG → keypoints ด้วย YOLOv8
# ────────────────────────────────────────────
def extract_keypoints_from_images(image_dir, yolo_model):
    """
    รัน YOLOv8 Pose บนรูปภาพแต่ละใบ
    คืน list ของ rows [x0,y0,...,x16,y16] (normalized 0-1)
    """
    import cv2

    rows = []
    image_files = [f for f in os.listdir(image_dir) 
                   if f.lower().endswith((".jpg", ".jpeg", ".png"))]

    for img_file in image_files:
        img_path = os.path.join(image_dir, img_file)
        try:
            frame = cv2.imread(img_path)
            if frame is None:
                continue

            results = yolo_model(frame, verbose=False, conf=0.5)

            if (results[0].keypoints is not None and 
                len(results[0].keypoints) > 0):
                kpts = results[0].keypoints.xyn[0].cpu().numpy()
                row = kpts.flatten().tolist()
                if len(row) == 34 and sum(row) > 0:
                    rows.append(row)
        except Exception as e:
            continue

    return rows


# ────────────────────────────────────────────
# PART 3: แปลง AVI → keypoints ด้วย YOLOv8
# ────────────────────────────────────────────
def extract_keypoints_from_videos(video_dir, yolo_model, max_frames_per_video=MAX_FRAMES_PER_VIDEO):
    """
    รัน YOLOv8 Pose บน frames ที่สุ่มจากแต่ละวิดีโอ
    คืน list ของ rows [x0,y0,...,x16,y16] (normalized 0-1)
    """
    import cv2

    rows = []
    video_files = [f for f in os.listdir(video_dir) 
                   if f.lower().endswith((".avi", ".mp4", ".mkv"))]

    for i, vid_file in enumerate(video_files):
        vid_path = os.path.join(video_dir, vid_file)
        try:
            cap = cv2.VideoCapture(vid_path)
            if not cap.isOpened():
                continue

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                cap.release()
                continue

            # สุ่มเลือก frames
            if total_frames > max_frames_per_video:
                selected = sorted(random.sample(range(total_frames), max_frames_per_video))
            else:
                selected = list(range(total_frames))

            for frame_idx in selected:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret or frame is None:
                    continue

                results = yolo_model(frame, verbose=False, conf=0.5)

                if (results[0].keypoints is not None and 
                    len(results[0].keypoints) > 0):
                    kpts = results[0].keypoints.xyn[0].cpu().numpy()
                    row = kpts.flatten().tolist()
                    if len(row) == 34 and sum(row) > 0:
                        rows.append(row)

            cap.release()

        except Exception as e:
            print(f"  ⚠️ Error processing video {vid_file}: {e}")
            continue

        if (i + 1) % 50 == 0:
            print(f"    Processed {i+1}/{len(video_files)} videos, {len(rows)} frames so far")

    return rows


# ────────────────────────────────────────────
# PART 4: รวบรวมข้อมูลจากทุกแหล่ง
# ────────────────────────────────────────────
def collect_csv_data(base_dir, label_class):
    """เก็บ keypoints จาก CSV files ใน directory (recursive)"""
    all_rows = []
    csv_files = []
    
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith(".csv"):
                csv_files.append(os.path.join(root, f))

    print(f"  พบ {len(csv_files)} CSV files")
    
    for i, csv_path in enumerate(csv_files):
        rows = parse_vertical_csv(csv_path)
        all_rows.extend(rows)
        
        if (i + 1) % 100 == 0:
            print(f"    Processed {i+1}/{len(csv_files)} CSVs, {len(all_rows)} frames so far")

    print(f"  ✅ ได้ {len(all_rows)} frames จาก CSV")
    return all_rows


def main():
    print("=" * 60)
    print("  🔄 PREPARE MULTI-POSE DATASET")
    print("  5 Classes: walk(0) / stand(1) / sit(2) / bend(3) / fall(4)")
    print("=" * 60)
    print()

    # เก็บข้อมูลแต่ละ class
    class_data = {
        0: [],  # walk
        1: [],  # stand
        2: [],  # sit
        3: [],  # bend
        4: [],  # fall
    }

    # ────────────────────────────────────
    # ส่วนที่ 1: CSV keypoints (Fall / No Fall)
    # ────────────────────────────────────
    print("━" * 50)
    print("📂 ส่วนที่ 1: CSV Keypoints (Fall / No Fall)")
    print("━" * 50)

    # Fall → class 4 (fall)
    for subfolder in ["Bed", "Chair", "Stand"]:
        path = os.path.join(DATASET_DIR, "Fall", subfolder)
        if os.path.exists(path):
            print(f"\n🔴 Fall/{subfolder} → class 4 (fall)")
            rows = collect_csv_data(path, LABEL_MAP["fall"])
            class_data[4].extend(rows)

    # No Fall/Stand → class 1 (stand)
    nf_stand = os.path.join(DATASET_DIR, "No Fall", "Stand")
    if os.path.exists(nf_stand):
        print(f"\n🟢 No Fall/Stand → class 1 (stand)")
        rows = collect_csv_data(nf_stand, LABEL_MAP["stand"])
        class_data[1].extend(rows)

    # No Fall/Chair → class 2 (sit)
    nf_chair = os.path.join(DATASET_DIR, "No Fall", "Chair")
    if os.path.exists(nf_chair):
        print(f"\n🟢 No Fall/Chair → class 2 (sit)")
        rows = collect_csv_data(nf_chair, LABEL_MAP["sit"])
        class_data[2].extend(rows)

    # No Fall/Bed → ข้ามไม่ใช้ (ไม่แน่ใจว่าเป็นท่าอะไร)
    print(f"\n⏭️  No Fall/Bed → ข้ามไม่ใช้")

    # ────────────────────────────────────
    # ส่วนที่ 2: รูปภาพ + วิดีโอ (archive)
    # ────────────────────────────────────
    print()
    print("━" * 50)
    print("📂 ส่วนที่ 2: Archive (JPG + AVI)")
    print("━" * 50)

    # ต้องโหลด YOLO สำหรับแปลง JPG/AVI
    yolo_model = None
    archive_sources = {
        # folder_name: (class_id, file_type)
        "walk": (0, "video"),       # 548 AVI
        "standing": (1, "image"),   # 1200 JPG
        "sitting": (2, "image"),    # 1200 JPG
        "sit": (2, "video"),        # 142 AVI
        "bending": (3, "image"),    # 1200 JPG
    }

    has_media = False
    for folder, (cls_id, ftype) in archive_sources.items():
        path = os.path.join(DATASET_DIR, "archive", folder)
        if os.path.exists(path):
            has_media = True
            break

    if has_media:
        print("\n🤖 Loading YOLOv8 Pose model...")
        try:
            from ultralytics import YOLO  # type: ignore
            yolo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yolov8n-pose.pt")
            yolo_model = YOLO(yolo_path)
            print("  ✅ YOLO loaded")
        except Exception as e:
            print(f"  ❌ Cannot load YOLO: {e}")
            print("  ⚠️ จะใช้เฉพาะข้อมูล CSV เท่านั้น")

    if yolo_model:
        for folder, (cls_id, ftype) in archive_sources.items():
            path = os.path.join(DATASET_DIR, "archive", folder)
            if not os.path.exists(path):
                print(f"\n⏭️  archive/{folder} → ไม่พบ")
                continue

            label_name = LABEL_NAMES[cls_id]
            print(f"\n🟡 archive/{folder} ({ftype}) → class {cls_id} ({label_name})")

            if ftype == "image":
                rows = extract_keypoints_from_images(path, yolo_model)
            else:  # video
                rows = extract_keypoints_from_videos(path, yolo_model)

            class_data[cls_id].extend(rows)
            print(f"  ✅ ได้ {len(rows)} frames")

    # ────────────────────────────────────
    # สรุปก่อน balance
    # ────────────────────────────────────
    print()
    print("━" * 50)
    print("📊 สรุปข้อมูลก่อน Balance")
    print("━" * 50)
    
    for cls_id, label_name in LABEL_NAMES.items():
        count = len(class_data[cls_id])
        print(f"  Class {cls_id} ({label_name:>6}): {count:>8} samples")

    # ────────────────────────────────────
    # Balance ข้อมูล (undersampling)
    # ────────────────────────────────────
    print()
    print("━" * 50)
    print("⚖️  Balancing Dataset (Undersampling)")
    print("━" * 50)

    # หาจำนวน class ที่น้อยที่สุด (ที่มีข้อมูล > 0)
    non_empty = {k: len(v) for k, v in class_data.items() if len(v) > 0}
    
    if len(non_empty) < 5:
        missing = [LABEL_NAMES[k] for k in range(5) if k not in non_empty]
        print(f"  ⚠️ ขาดข้อมูล class: {', '.join(missing)}")
    
    if not non_empty:
        print("  ❌ ไม่มีข้อมูลเลย!")
        return

    min_count = min(non_empty.values())
    target = min_count
    print(f"  Target per class: {target} samples (based on smallest class)")

    balanced_data = []
    for cls_id in sorted(non_empty.keys()):
        data = class_data[cls_id]
        label_name = LABEL_NAMES[cls_id]
        
        if len(data) > target:
            sampled = random.sample(data, target)
        else:
            sampled = data
        
        for row in sampled:
            balanced_data.append(row + [cls_id])
        
        print(f"  Class {cls_id} ({label_name:>6}): {len(data):>8} → {len(sampled):>8} samples")

    # Shuffle
    random.shuffle(balanced_data)

    # ────────────────────────────────────
    # บันทึก CSV
    # ────────────────────────────────────
    print()
    print("━" * 50)
    print("💾 Saving Dataset")
    print("━" * 50)

    # Header
    header = []
    for i in range(17):
        header.extend([f"x{i}", f"y{i}"])
    header.append("class")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(balanced_data)

    print(f"  ✅ Saved: {OUTPUT_CSV}")
    print(f"  📝 Total samples: {len(balanced_data)}")
    print(f"  📝 Features: 34 (17 keypoints × 2)")
    print(f"  📝 Classes: {len(non_empty)}")

    # บันทึก label mapping
    labels_info = {
        "labels": LABEL_MAP,
        "names": LABEL_NAMES,
        "total_samples": len(balanced_data),
        "samples_per_class": {
            LABEL_NAMES[k]: min(len(class_data[k]), target) 
            for k in sorted(non_empty.keys())
        }
    }
    # Convert int keys to string for JSON
    labels_info["names"] = {str(k): v for k, v in LABEL_NAMES.items()}
    
    with open(LABELS_JSON, "w", encoding="utf-8") as f:
        json.dump(labels_info, f, indent=2, ensure_ascii=False)

    print(f"  ✅ Saved: {LABELS_JSON}")

    print()
    print("=" * 60)
    print("  ✅ DONE! ขั้นตอนต่อไป: python train_multipose.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
