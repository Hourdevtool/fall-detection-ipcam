"""
train_multipose.py — เทรน Multi-Pose Classification Model

ใช้ข้อมูลจาก multipose_dataset.csv ที่สร้างจาก prepare_dataset.py
ใช้ HistGradientBoostingClassifier (เร็วกว่า RF ~8-10x และแม่นยำกว่า)
พร้อม GroupShuffleSplit / GroupKFold เพื่อกัน frame-leakage ข้ามวิดีโอ

5 Classes:
  0 = walk   (เดิน)
  1 = stand  (ยืน)
  2 = sit    (นั่ง)
  3 = bend   (ก้มเก็บของ)
  4 = fall   (ล้ม)

Usage:
  python Tools/train_multipose.py
"""

import json
import os
import sys
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import (
    GroupKFold,
    GroupShuffleSplit,
    StratifiedKFold,
    train_test_split,
)
from sklearn.utils.class_weight import compute_sample_weight

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

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


def _make_model():
    return HistGradientBoostingClassifier(
        max_iter=250,
        max_depth=8,
        learning_rate=0.06,
        min_samples_leaf=20,
        l2_regularization=0.1,
        random_state=RANDOM_STATE,
    )


def main():
    print("=" * 60)
    print("  🧠 TRAIN MULTI-POSE CLASSIFICATION MODEL (HistGB)")
    print("=" * 60)
    print()

    if not os.path.exists(DATASET_CSV):
        print(f"  ❌ ไม่พบไฟล์ {DATASET_CSV}")
        print("  👉 รัน Tools/prepare_dataset.py ก่อน!")
        sys.exit(1)

    df = pd.read_csv(DATASET_CSV)
    print(f"📂 Loaded {len(df)} samples, {df.shape[1]} columns")

    df = df.dropna()
    groups = df["group"].values if "group" in df.columns else None
    drop_cols = ["class"] + (["group"] if "group" in df.columns else [])
    feature_cols = [c for c in df.columns if c not in drop_cols]
    X = df[feature_cols].values.astype(np.float32)
    y = df["class"].values.astype(np.int32)

    print("📊 Dataset Summary:")
    for cls_id in sorted(np.unique(y)):
        cnt = int((y == cls_id).sum())
        print(f"  Class {cls_id} ({LABEL_NAMES.get(cls_id, '?'):>6} / {LABEL_NAMES_TH.get(cls_id, '?')}): {cnt:>6}")
    print(f"📐 Feature shape: {X.shape}\n")

    if groups is not None:
        splitter = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
        train_idx, test_idx = next(splitter.split(X, y, groups))
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        print(f"✂️  GroupShuffleSplit (no clip leakage): Train={len(X_train)}, Test={len(X_test)}\n")
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
        )
        print(f"✂️  Stratified Split: Train={len(X_train)}, Test={len(X_test)}\n")

    t0 = time.perf_counter()
    model = _make_model()
    sw_train = compute_sample_weight("balanced", y_train)
    model.fit(X_train, y_train, sample_weight=sw_train)
    fit_sec = time.perf_counter() - t0

    t1 = time.perf_counter()
    y_pred = model.predict(X_test)
    _ = model.predict_proba(X_test[:1])
    single_ms = (time.perf_counter() - t1) * 1000.0 / max(1, len(X_test))

    acc = accuracy_score(y_test, y_pred)
    sit_mask = y_test == 2
    sit_to_fall = float((y_pred[sit_mask] == 4).mean()) if sit_mask.any() else 0.0

    # Benchmark single-sample predict_proba latency directly
    sample1 = X_test[:1]
    tb = time.perf_counter()
    for _ in range(50):
        model.predict_proba(sample1)
    inf_ms_single = (time.perf_counter() - tb) * 1000.0 / 50.0

    print(f"✅ Accuracy: {acc*100:.2f}% | Sit->Fall rate: {sit_to_fall*100:.2f}%")
    print(f"⚡ Fit: {fit_sec:.1f}s | Single-sample predict_proba: {inf_ms_single:.2f} ms\n")

    target_names = [f"{LABEL_NAMES[i]} ({LABEL_NAMES_TH[i]})" for i in sorted(np.unique(y))]
    print("📋 Classification Report:")
    print(classification_report(y_test, y_pred, target_names=target_names))

    print("📊 Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    classes_sorted = sorted(np.unique(y))
    header = "  " + "  ".join(f"{LABEL_NAMES_TH.get(i, '?'):>5}" for i in classes_sorted)
    print(f"  {'Predicted →':>12}\n  {'Actual ↓':>12} {header}")
    for i, row in enumerate(cm):
        cls_name = LABEL_NAMES_TH.get(classes_sorted[i], "?")
        print(f"  {cls_name:>12}  " + "  ".join(f"{v:>5}" for v in row))
    print()

    # 5-fold group CV
    print("🔄 5-Fold Cross-Validation...")
    cv_scores = []
    if groups is not None:
        gkf = GroupKFold(n_splits=5)
        splits = gkf.split(X, y, groups)
    else:
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
        splits = skf.split(X, y)

    for tr, te in splits:
        m_cv = _make_model()
        m_cv.fit(X[tr], y[tr], sample_weight=compute_sample_weight("balanced", y[tr]))
        cv_scores.append(accuracy_score(y[te], m_cv.predict(X[te])))
    cv_scores = np.array(cv_scores, dtype=np.float64)
    print(f"  Scores: {[f'{s:.4f}' for s in cv_scores]}")
    print(f"  Mean: {cv_scores.mean():.4f} (±{cv_scores.std():.4f})\n")

    # Retrain on full dataset? Keeping held-out verified metrics + fit on train split or full?
    # Fitting on full dataset gives maximum real-world accuracy while logging verified CV/test stats.
    final_model = _make_model()
    final_model.fit(X, y, sample_weight=compute_sample_weight("balanced", y))

    joblib.dump(final_model, MODEL_OUTPUT)
    print(f"💾 Saved: {MODEL_OUTPUT} ({os.path.getsize(MODEL_OUTPUT) / 1024 / 1024:.2f} MB)")

    labels_info = json.load(open(LABELS_JSON, "r", encoding="utf-8")) if os.path.exists(LABELS_JSON) else {}
    labels_info.update({
        "model_file": "multipose_model.pkl",
        "model_type": "HistGradientBoostingClassifier",
        "accuracy": float(acc),
        "sit_to_fall_rate": float(sit_to_fall),
        "cv_mean": float(cv_scores.mean()),
        "cv_std": float(cv_scores.std()),
        "n_classes": int(len(classes_sorted)),
        "n_features": int(X.shape[1]),
        "train_samples": int(len(X_train)),
        "test_samples": int(len(X_test)),
        "total_samples": int(len(X)),
    })
    with open(LABELS_JSON, "w", encoding="utf-8") as f:
        json.dump(labels_info, f, indent=2, ensure_ascii=False)
    print(f"✅ Updated: {LABELS_JSON}")


if __name__ == "__main__":
    main()
