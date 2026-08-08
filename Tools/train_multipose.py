"""
train_multipose.py — เทรน Multi-Pose Classification Model

ใช้ข้อมูลจาก multipose_dataset.csv ที่สร้างจาก prepare_dataset.py

5 Classes:
  0 = walk   (เดิน)
  1 = stand  (ยืน)
  2 = sit    (นั่ง)
  3 = bend   (ก้มเก็บของ)
  4 = fall   (ล้ม)

Usage:
  cd d:\\buff_p\\Tools
  python train_multipose.py
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import (
    classification_report, confusion_matrix, accuracy_score
)
from sklearn.preprocessing import LabelEncoder

# ────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_CSV = os.path.join(TOOLS_DIR, "multipose_dataset.csv")
LABELS_JSON = os.path.join(TOOLS_DIR, "pose_labels.json")
MODEL_OUTPUT = os.path.join(TOOLS_DIR, "multipose_model.pkl")

LABEL_NAMES = {
    0: "walk",
    1: "stand",
    2: "sit",
    3: "bend",
    4: "fall",
}

LABEL_NAMES_TH = {
    0: "เดิน",
    1: "ยืน",
    2: "นั่ง",
    3: "ก้ม",
    4: "ล้ม",
}

TEST_SIZE = 0.2
RANDOM_STATE = 42


def main():
    print("=" * 60)
    print("  🧠 TRAIN MULTI-POSE CLASSIFICATION MODEL")
    print("=" * 60)
    print()

    # ────────────────────────────────────
    # 1. โหลดข้อมูล
    # ────────────────────────────────────
    print("📂 Loading dataset...")
    if not os.path.exists(DATASET_CSV):
        print(f"  ❌ ไม่พบไฟล์ {DATASET_CSV}")
        print(f"  👉 รัน prepare_dataset.py ก่อน!")
        sys.exit(1)

    df = pd.read_csv(DATASET_CSV)
    print(f"  ✅ Loaded {len(df)} samples, {df.shape[1]} columns")
    print()

    # ────────────────────────────────────
    # 2. ตรวจสอบข้อมูล
    # ────────────────────────────────────
    print("📊 Dataset Summary:")
    print("-" * 40)
    for cls_id in sorted(df["class"].unique()):
        count = len(df[df["class"] == cls_id])
        name = LABEL_NAMES.get(cls_id, f"unknown_{cls_id}")
        name_th = LABEL_NAMES_TH.get(cls_id, "?")
        print(f"  Class {cls_id} ({name:>6} / {name_th}): {count:>6} samples")
    print(f"  {'Total':>22}: {len(df):>6} samples")
    print()

    # ตรวจหา NaN
    nan_count = df.isnull().sum().sum()
    if nan_count > 0:
        print(f"  ⚠️ พบ NaN {nan_count} จุด — จะลบแถวที่มี NaN")
        df = df.dropna()
        print(f"  ✅ เหลือ {len(df)} samples หลังลบ NaN")
        print()

    # ────────────────────────────────────
    # 3. แยก Features / Labels
    # ────────────────────────────────────
    X = df.drop("class", axis=1).values
    y = df["class"].values

    print(f"📐 Feature shape: {X.shape}")
    print(f"🏷️  Label shape: {y.shape}")
    print(f"🏷️  Classes: {sorted(np.unique(y))}")
    print()

    # ────────────────────────────────────
    # 4. Train / Test Split
    # ────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )

    print(f"✂️  Train/Test Split ({int((1-TEST_SIZE)*100)}/{int(TEST_SIZE*100)}):")
    print(f"  Train: {len(X_train)} samples")
    print(f"  Test:  {len(X_test)} samples")
    print()

    # ────────────────────────────────────
    # 5. เทรน Random Forest
    # ────────────────────────────────────
    print("━" * 50)
    print("🌲 Training Random Forest...")
    print("━" * 50)

    rf_model = RandomForestClassifier(
        n_estimators=200,
        max_depth=20,
        min_samples_split=5,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=RANDOM_STATE,
        n_jobs=-1,
        verbose=0
    )

    rf_model.fit(X_train, y_train)
    rf_pred = rf_model.predict(X_test)
    rf_acc = accuracy_score(y_test, rf_pred)

    print(f"\n  ✅ Random Forest Accuracy: {rf_acc*100:.2f}%")
    print()

    # Classification Report
    target_names = [f"{LABEL_NAMES[i]} ({LABEL_NAMES_TH[i]})" 
                    for i in sorted(np.unique(y))]
    
    print("📋 Classification Report (Random Forest):")
    print("-" * 55)
    print(classification_report(y_test, rf_pred, target_names=target_names))

    # Confusion Matrix
    print("📊 Confusion Matrix:")
    cm = confusion_matrix(y_test, rf_pred)
    
    # Pretty print
    header = "  " + "  ".join([f"{LABEL_NAMES_TH.get(i, '?'):>5}" for i in sorted(np.unique(y))])
    print(f"  {'Predicted →':>12}")
    print(f"  {'Actual ↓':>12} {header}")
    for i, row in enumerate(cm):
        cls_name = LABEL_NAMES_TH.get(sorted(np.unique(y))[i], "?")
        row_str = "  ".join([f"{v:>5}" for v in row])
        print(f"  {cls_name:>12}  {row_str}")
    print()

    # ────────────────────────────────────
    # 6. Cross-Validation
    # ────────────────────────────────────
    print("🔄 5-Fold Cross-Validation...")
    cv_scores = cross_val_score(rf_model, X, y, cv=5, scoring="accuracy", n_jobs=-1)
    print(f"  Scores: {[f'{s:.4f}' for s in cv_scores]}")
    print(f"  Mean: {cv_scores.mean():.4f} (±{cv_scores.std():.4f})")
    print()

    # ────────────────────────────────────
    # 7. Feature Importance
    # ────────────────────────────────────
    print("🔑 Top 10 Feature Importance:")
    feature_names = [f"{'x' if i%2==0 else 'y'}{i//2}" for i in range(34)]
    kp_labels = []
    for i in range(17):
        kp_name = [
            "Nose", "L_Eye", "R_Eye", "L_Ear", "R_Ear",
            "L_Shoulder", "R_Shoulder", "L_Elbow", "R_Elbow",
            "L_Wrist", "R_Wrist", "L_Hip", "R_Hip",
            "L_Knee", "R_Knee", "L_Ankle", "R_Ankle"
        ][i]
        kp_labels.extend([f"x_{kp_name}", f"y_{kp_name}"])

    importances = rf_model.feature_importances_
    indices = np.argsort(importances)[::-1]
    
    for rank, idx in enumerate(indices[:10]):
        print(f"  {rank+1:>2}. {kp_labels[idx]:>15}: {importances[idx]:.4f}")
    print()

    # ────────────────────────────────────
    # 8. บันทึกโมเดล
    # ────────────────────────────────────
    print("━" * 50)
    print("💾 Saving Model...")
    print("━" * 50)

    joblib.dump(rf_model, MODEL_OUTPUT)
    print(f"  ✅ Saved: {MODEL_OUTPUT}")
    print(f"  📝 Model size: {os.path.getsize(MODEL_OUTPUT) / 1024 / 1024:.1f} MB")

    # อัพเดท labels JSON
    if os.path.exists(LABELS_JSON):
        with open(LABELS_JSON, "r", encoding="utf-8") as f:
            labels_info = json.load(f)
    else:
        labels_info = {}

    labels_info["model_file"] = "multipose_model.pkl"
    labels_info["accuracy"] = float(rf_acc)
    labels_info["cv_mean"] = float(cv_scores.mean())
    labels_info["cv_std"] = float(cv_scores.std())
    labels_info["n_classes"] = len(np.unique(y))
    labels_info["n_features"] = X.shape[1]
    labels_info["train_samples"] = len(X_train)
    labels_info["test_samples"] = len(X_test)

    with open(LABELS_JSON, "w", encoding="utf-8") as f:
        json.dump(labels_info, f, indent=2, ensure_ascii=False)

    print(f"  ✅ Updated: {LABELS_JSON}")

    # ────────────────────────────────────
    # 9. สรุป
    # ────────────────────────────────────
    print()
    print("=" * 60)
    print(f"  ✅ TRAINING COMPLETE!")
    print(f"  📊 Accuracy: {rf_acc*100:.2f}%")
    print(f"  📊 CV Mean:  {cv_scores.mean()*100:.2f}%")
    print(f"  💾 Model:    {MODEL_OUTPUT}")
    print()
    print("  ขั้นตอนต่อไป:")
    print("  1. ตรวจสอบ accuracy ว่าพอใจหรือไม่")
    print("  2. ถ้าพอใจ → แก้ detection.py ให้ใช้โมเดลใหม่")
    print("  3. ทดสอบกับกล้องจริง")
    print("=" * 60)


if __name__ == "__main__":
    main()
