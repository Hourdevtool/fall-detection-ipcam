"""
generate_training_plots.py — สร้างกราฟประเมินผลการฝึกสอนโมเดล Multi-Pose (สไตล์ Ultralytics/YOLO)

อ่านข้อมูลจาก Tools/multipose_dataset.csv (63 features)
แบ่งข้อมูลด้วย GroupShuffleSplit (80/20, random_state=42) แบบเดียวกับ train_multipose.py
ฝึกสอน HistGradientBoostingClassifier และสร้างกราฟทั้งหมด 8 รูปไว้ใน Tools/training_plots/:
  1. F1_curve.png
  2. P_curve.png
  3. PR_curve.png
  4. R_curve.png
  5. confusion_matrix.png
  6. confusion_matrix_normalized.png
  7. labels.png
  8. loss_curve.png
"""

import json
import os
import sys
import time

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
    precision_recall_curve,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.utils.class_weight import compute_sample_weight

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_CSV = os.path.join(TOOLS_DIR, "multipose_dataset.csv")
MODEL_PATH = os.path.join(TOOLS_DIR, "multipose_model.pkl")
OUT_DIR = os.path.join(TOOLS_DIR, "training_plots")

CLASS_NAMES = ["walk", "stand", "sit", "bend", "fall"]
RANDOM_STATE = 42
TEST_SIZE = 0.2


def make_model():
    return HistGradientBoostingClassifier(
        max_iter=250,
        max_depth=8,
        learning_rate=0.06,
        min_samples_leaf=20,
        l2_regularization=0.1,
        random_state=RANDOM_STATE,
    )


def compute_ovr_curves(y_true, y_proba, n_classes, n_points=1000):
    """Compute Precision, Recall, F1 vs Confidence threshold (0..1) per class."""
    px = np.linspace(0.0, 1.0, n_points)
    p_curves = np.zeros((n_classes, n_points), dtype=np.float64)
    r_curves = np.zeros((n_classes, n_points), dtype=np.float64)
    f1_curves = np.zeros((n_classes, n_points), dtype=np.float64)

    for c in range(n_classes):
        y_bin = (y_true == c).astype(np.int32)
        scores = y_proba[:, c]
        order = np.argsort(-scores)
        scores_sorted = scores[order]
        y_sorted = y_bin[order]

        tp_cum = np.cumsum(y_sorted)
        fp_cum = np.cumsum(1 - y_sorted)
        total_pos = int(y_bin.sum())

        # For each threshold t, predictions are scores >= t
        # np.searchsorted on descending array via negated scores
        neg_scores = -scores_sorted
        idx = np.searchsorted(neg_scores, -px, side="right")

        tp = np.where(idx > 0, tp_cum[np.clip(idx - 1, 0, len(tp_cum) - 1)], 0)
        fp = np.where(idx > 0, fp_cum[np.clip(idx - 1, 0, len(fp_cum) - 1)], 0)

        prec = np.where((tp + fp) > 0, tp / np.maximum(tp + fp, 1), 1.0)
        rec = tp / max(total_pos, 1)
        f1 = np.where((prec + rec) > 0, 2.0 * prec * rec / np.maximum(prec + rec, 1e-12), 0.0)

        p_curves[c] = prec
        r_curves[c] = rec
        f1_curves[c] = f1

    return px, p_curves, r_curves, f1_curves


def plot_mc_curve(px, py, save_path, xlabel="Confidence", ylabel="Metric", title="", best_label=None):
    """Ultralytics/YOLO style multi-class curve with bold blue mean line."""
    fig, ax = plt.subplots(1, 1, figsize=(9, 6), tight_layout=True)

    for i, name in enumerate(CLASS_NAMES):
        ax.plot(px, py[i], linewidth=1.2, alpha=0.85, label=name)

    mean_y = py.mean(axis=0)
    if best_label is None:
        best_i = int(np.argmax(mean_y))
        best_label = f"all classes {mean_y[best_i]:.2f} at {px[best_i]:.3f}"

    ax.plot(px, mean_y, linewidth=3.0, color="blue", label=best_label)
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_title(title, fontsize=13)
    ax.legend(bbox_to_anchor=(1.04, 1), loc="upper left", frameon=True)
    fig.savefig(save_path, dpi=250, bbox_inches="tight")
    plt.close(fig)


def plot_pr_curve(y_true, y_proba, save_path):
    """Ultralytics/YOLO style Precision-Recall Curve."""
    fig, ax = plt.subplots(1, 1, figsize=(9, 6), tight_layout=True)
    recall_grid = np.linspace(0.0, 1.0, 1000)
    interp_precs = []
    aps = []

    for c, name in enumerate(CLASS_NAMES):
        y_bin = (y_true == c).astype(np.int32)
        prec, rec, _ = precision_recall_curve(y_bin, y_proba[:, c])
        ap = average_precision_score(y_bin, y_proba[:, c])
        aps.append(ap)

        # Interpolate precision over recall_grid (rec is descending in sklearn)
        p_interp = np.interp(recall_grid, rec[::-1], prec[::-1])
        interp_precs.append(p_interp)
        ax.plot(rec, prec, linewidth=1.2, alpha=0.85, label=f"{name} {ap:.3f}")

    mean_prec = np.mean(interp_precs, axis=0)
    macro_ap = float(np.mean(aps))
    ax.plot(
        recall_grid,
        mean_prec,
        linewidth=3.0,
        color="blue",
        label=f"all classes {macro_ap:.3f} mAP",
    )
    ax.set_xlabel("Recall", fontsize=11)
    ax.set_ylabel("Precision", fontsize=11)
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_title("Precision-Recall Curve", fontsize=13)
    ax.legend(bbox_to_anchor=(1.04, 1), loc="upper left", frameon=True)
    fig.savefig(save_path, dpi=250, bbox_inches="tight")
    plt.close(fig)
    return {CLASS_NAMES[i]: float(aps[i]) for i in range(len(CLASS_NAMES))}, macro_ap


def plot_confusion(cm, save_path, normalized=False):
    """Ultralytics/YOLO style Confusion Matrix (Y=Predicted, X=True, Blues)."""
    # Transpose so rows = Predicted, cols = True (matching YOLO layout)
    mat = cm.T.astype(np.float64)
    if normalized:
        col_sums = mat.sum(axis=0, keepdims=True)
        mat = np.divide(mat, np.maximum(col_sums, 1.0))

    fig, ax = plt.subplots(1, 1, figsize=(8.5, 7), tight_layout=True)
    im = ax.imshow(
        mat,
        interpolation="nearest",
        cmap=plt.cm.Blues,
        vmin=0.0,
        vmax=1.0 if normalized else None,
    )
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.ax.tick_params(labelsize=9)

    ticks = np.arange(len(CLASS_NAMES))
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    ax.set_xticklabels(CLASS_NAMES, rotation=90, fontsize=11)
    ax.set_yticklabels(CLASS_NAMES, fontsize=11)
    ax.set_xlabel("True", fontsize=11, labelpad=10)
    ax.set_ylabel("Predicted", fontsize=11, labelpad=10)
    ax.set_title(
        "Confusion Matrix Normalized" if normalized else "Confusion Matrix",
        fontsize=12,
        pad=14,
    )

    thresh = mat.max() * 0.55
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            val = mat[i, j]
            if normalized:
                txt = f"{val:.2f}" if val >= 0.005 else ""
            else:
                txt = f"{int(val)}" if val > 0 else ""
            if txt:
                ax.text(
                    j,
                    i,
                    txt,
                    ha="center",
                    va="center",
                    color="white" if val > thresh else "black",
                    fontsize=10,
                )

    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.savefig(save_path, dpi=250, bbox_inches="tight")
    plt.close(fig)


def plot_labels_summary(df, save_path):
    """4-panel dataset & pose-geometry summary matching Ultralytics labels.jpg."""
    fig, axes = plt.subplots(2, 2, figsize=(10, 10), tight_layout=True)

    # Panel 1 (Top-left): Class instance counts
    ax = axes[0, 0]
    counts = [int((df["class"] == i).sum()) for i in range(len(CLASS_NAMES))]
    bars = ax.bar(CLASS_NAMES, counts, color="#1a3cff", width=0.72)
    ax.set_ylabel("instances", fontsize=11)
    ax.tick_params(axis="x", rotation=90, labelsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for bar, cnt in zip(bars, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            cnt + max(counts) * 0.015,
            f"{cnt:,}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    # Panel 2 (Top-right): Sampled normalized pose aspect-ratio boxes
    ax = axes[0, 1]
    rng = np.random.default_rng(RANDOM_STATE)
    sample_idx = rng.choice(len(df), size=min(400, len(df)), replace=False)
    ar_vals = np.clip(df["f51"].values[sample_idx], 0.2, 3.0)
    for ar in ar_vals:
        if ar >= 1.0:
            w, h = 0.85, 0.85 / ar
        else:
            h, w = 0.85, 0.85 * ar
        rect = Rectangle(
            (0.5 - w / 2.0, 0.5 - h / 2.0),
            w,
            h,
            linewidth=0.5,
            edgecolor="#2643d8",
            facecolor="none",
            alpha=0.28,
        )
        ax.add_patch(rect)
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.axis("off")

    # Panel 3 (Bottom-left): 2D histogram of normalized nose/head (nx, ny)
    ax = axes[1, 0]
    x_head = np.clip(df["f0"].values, -1.0, 1.0)
    y_head = np.clip(df["f1"].values, -1.0, 1.0)
    mask_vis = df["f2"].values > 0.5
    ax.hist2d(x_head[mask_vis], y_head[mask_vis], bins=45, cmap="Blues", cmin=1)
    ax.set_xlabel("head x (normalized)", fontsize=11)
    ax.set_ylabel("head y (normalized)", fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Panel 4 (Bottom-right): 2D histogram of pose aspect_ratio vs torso_angle
    ax = axes[1, 1]
    ar_all = np.clip(df["f51"].values, 0.0, 3.0)
    ang_all = np.clip(df["f52"].values * 90.0, 0.0, 90.0)
    ax.hist2d(ar_all, ang_all, bins=45, cmap="Blues", cmin=1)
    ax.set_xlabel("aspect ratio (width / height)", fontsize=11)
    ax.set_ylabel("torso angle (degrees)", fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.savefig(save_path, dpi=250, bbox_inches="tight")
    plt.close(fig)


def plot_loss_curve(model, save_path):
    """Training vs Validation Multiclass Log-Loss curve across boosting iterations."""
    train_loss = -np.asarray(model.train_score_, dtype=np.float64)
    val_loss = -np.asarray(model.validation_score_, dtype=np.float64)
    iters = np.arange(len(train_loss))

    fig, ax = plt.subplots(1, 1, figsize=(9, 5.5), tight_layout=True)
    ax.plot(iters, train_loss, color="#1a3cff", linewidth=2.2, label=f"Training Log-Loss (final: {train_loss[-1]:.4f})")
    ax.plot(iters, val_loss, color="#e65100", linewidth=2.2, linestyle="--", label=f"Validation Log-Loss (final: {val_loss[-1]:.4f})")
    ax.set_xlabel("Boosting Iteration", fontsize=11)
    ax.set_ylabel("Multiclass Log-Loss", fontsize=11)
    ax.set_title("Training vs Validation Loss Curve (HistGradientBoostingClassifier)", fontsize=13)
    ax.set_xlim(0, len(train_loss) - 1)
    ax.set_ylim(0.0, max(float(train_loss[0]), float(val_loss[0])) * 1.05)
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="upper right", frameon=True, fontsize=10)
    fig.savefig(save_path, dpi=250, bbox_inches="tight")
    plt.close(fig)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.exists(DATASET_CSV):
        print(f"❌ ไม่พบไฟล์ {DATASET_CSV}")
        sys.exit(1)

    print(f"📂 Loading {DATASET_CSV} ...")
    df = pd.read_csv(DATASET_CSV).dropna()
    groups = df["group"].values if "group" in df.columns else None
    drop_cols = ["class"] + (["group"] if "group" in df.columns else [])
    feature_cols = [c for c in df.columns if c not in drop_cols]
    X = df[feature_cols].values.astype(np.float32)
    y = df["class"].values.astype(np.int32)
    print(f"✅ Loaded {len(df):,} samples × {X.shape[1]} features")

    splitter = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    train_idx, test_idx = next(splitter.split(X, y, groups))
    X_train, X_test = X[train_idx], X[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]
    print(f"✂️  Split: Train={len(X_train):,}, Test={len(X_test):,}")

    t0 = time.perf_counter()
    model = make_model()
    sw_train = compute_sample_weight("balanced", y_train)
    model.fit(X_train, y_train, sample_weight=sw_train)
    fit_sec = time.perf_counter() - t0
    print(f"⚡ Holdout model fitted in {fit_sec:.2f}s")

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    sit_to_fall = float((y_pred[y_test == 2] == 4).mean())
    cm = confusion_matrix(y_test, y_pred, labels=list(range(len(CLASS_NAMES))))

    print(f"✅ Holdout Test Accuracy: {acc * 100:.2f}% | Sit→Fall: {sit_to_fall * 100:.2f}%")
    print("\n" + classification_report(y_test, y_pred, target_names=CLASS_NAMES, digits=4))

    # 1–4. Confidence & PR curves
    px, p_curves, r_curves, f1_curves = compute_ovr_curves(y_test, y_proba, len(CLASS_NAMES))
    plot_mc_curve(px, f1_curves, os.path.join(OUT_DIR, "F1_curve.png"), "Confidence", "F1", "F1-Confidence Curve")
    plot_mc_curve(px, p_curves, os.path.join(OUT_DIR, "P_curve.png"), "Confidence", "Precision", "Precision-Confidence Curve")
    plot_mc_curve(px, r_curves, os.path.join(OUT_DIR, "R_curve.png"), "Confidence", "Recall", "Recall-Confidence Curve")
    ap_per_class, macro_ap = plot_pr_curve(y_test, y_proba, os.path.join(OUT_DIR, "PR_curve.png"))

    # 5–6. Confusion Matrices
    plot_confusion(cm, os.path.join(OUT_DIR, "confusion_matrix.png"), normalized=False)
    plot_confusion(cm, os.path.join(OUT_DIR, "confusion_matrix_normalized.png"), normalized=True)

    # 7. Dataset Labels & Pose Summary
    plot_labels_summary(df, os.path.join(OUT_DIR, "labels.png"))

    # 8. Loss Curve (use saved production model if available, else holdout model)
    loss_model = joblib.load(MODEL_PATH) if os.path.exists(MODEL_PATH) else model
    plot_loss_curve(loss_model, os.path.join(OUT_DIR, "loss_curve.png"))

    summary = {
        "total_samples": int(len(df)),
        "train_samples": int(len(X_train)),
        "test_samples": int(len(X_test)),
        "holdout_fit_sec": round(fit_sec, 2),
        "holdout_accuracy": float(acc),
        "sit_to_fall_rate": float(sit_to_fall),
        "macro_ap": macro_ap,
        "ap_per_class": ap_per_class,
        "confusion_matrix_rows_true_cols_pred": cm.tolist(),
        "classification_report": classification_report(
            y_test, y_pred, target_names=CLASS_NAMES, output_dict=True
        ),
    }
    with open(os.path.join(OUT_DIR, "metrics_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 Generated 8 training plots in: {OUT_DIR}")


if __name__ == "__main__":
    main()
