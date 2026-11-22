"""
generate_algorithm_flowcharts.py — สร้างแผนภาพการทำงานของอัลกอริทึมเทรนโมเดล
และโครงสร้าง Decision Tree ในรูปแบบ Flowchart ขาว-ดำมาตรฐาน (สำหรับรายงาน/เอกสาร)

Output:
  - Tools/training_plots/flowchart_training_algorithm.png
  - Tools/training_plots/flowchart_decision_tree_fall.png
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyBboxPatch, Polygon


FONT_FAMILY = "Leelawadee UI"
LINE_COLOR = "#000000"
FILL_COLOR = "#FFFFFF"
TEXT_COLOR = "#000000"
SHAPE_LW = 1.8
ARROW_LW = 1.25


def _setup_axes(figsize, xlim, ylim):
    plt.rcParams["font.family"] = FONT_FAMILY
    fig, ax = plt.subplots(figsize=figsize, dpi=300)
    fig.patch.set_facecolor(FILL_COLOR)
    ax.set_facecolor(FILL_COLOR)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.axis("off")
    return fig, ax


def draw_oval(ax, cx, cy, w, h, text, fontsize=11):
    patch = Ellipse(
        (cx, cy), width=w, height=h,
        facecolor=FILL_COLOR, edgecolor=LINE_COLOR, linewidth=SHAPE_LW, zorder=3
    )
    ax.add_patch(patch)
    ax.text(
        cx, cy, text, ha="center", va="center",
        fontsize=fontsize, color=TEXT_COLOR, zorder=4, linespacing=1.3
    )


def draw_rect(ax, cx, cy, w, h, text, fontsize=10.5, rounding=0.14):
    patch = FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle=f"round,pad=0,rounding_size={rounding}",
        facecolor=FILL_COLOR, edgecolor=LINE_COLOR, linewidth=SHAPE_LW, zorder=3
    )
    ax.add_patch(patch)
    ax.text(
        cx, cy, text, ha="center", va="center",
        fontsize=fontsize, color=TEXT_COLOR, zorder=4, linespacing=1.3
    )


def draw_diamond(ax, cx, cy, w, h, text, fontsize=10):
    pts = [
        (cx, cy + h / 2),
        (cx + w / 2, cy),
        (cx, cy - h / 2),
        (cx - w / 2, cy),
    ]
    patch = Polygon(
        pts, closed=True,
        facecolor=FILL_COLOR, edgecolor=LINE_COLOR, linewidth=SHAPE_LW, zorder=3
    )
    ax.add_patch(patch)
    ax.text(
        cx, cy, text, ha="center", va="center",
        fontsize=fontsize, color=TEXT_COLOR, zorder=4, linespacing=1.25
    )


def draw_arrow(ax, x1, y1, x2, y2):
    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(
            arrowstyle="-|>",
            color=LINE_COLOR,
            lw=ARROW_LW,
            mutation_scale=13,
            shrinkA=0,
            shrinkB=0,
        ),
        zorder=2,
    )


def draw_ortho_arrow(ax, points):
    """Draw a multi-segment orthogonal polyline ending with a crisp arrowhead."""
    xs = [p[0] for p in points[:-1]]
    ys = [p[1] for p in points[:-1]]
    if len(points) > 2:
        ax.plot(xs, ys, color=LINE_COLOR, lw=ARROW_LW, solid_joinstyle="miter", zorder=2)
    draw_arrow(ax, points[-2][0], points[-2][1], points[-1][0], points[-1][1])


def generate_training_flowchart(out_path):
    """แผนภาพการทำงานของอัลกอริทึม HistGradientBoostingClassifier (Training Pipeline)."""
    fig, ax = _setup_axes(figsize=(7.8, 12.8), xlim=(-4.2, 5.2), ylim=(-0.4, 15.6))

    cx = 0.0
    rw = 5.4
    rh = 1.02

    # Positions (top to bottom)
    y_start = 14.85
    y_1 = 13.35
    y_2 = 11.75
    y_3 = 10.15
    y_4 = 8.45
    y_5 = 6.85
    y_6 = 5.25
    y_dec = 3.30
    y_7 = 1.45
    y_end = 0.15

    # Shapes
    draw_oval(ax, cx, y_start, 2.7, 0.85, "เริ่มต้น", fontsize=11.5)
    draw_rect(ax, cx, y_1, rw, rh, "รับข้อมูลจุดข้อต่อร่างกาย 17 จุด\n(YOLO Pose Keypoints)", fontsize=10.5)
    draw_rect(ax, cx, y_2, rw, rh, "สกัดคุณลักษณะ 63 ฟีเจอร์\n(มุมลำตัว, มุมต้นขา, สัดส่วนกว้าง/สูง)", fontsize=10.5)
    draw_rect(ax, cx, y_3, rw, rh, "จัดกลุ่มค่าเป็นช่วง (Histogram Binning)\nและแบ่งข้อมูล Train / Test (80 / 20)", fontsize=10.5)
    draw_rect(ax, cx, y_4, rw, rh, "สร้างต้นไม้ตัดสินใจ (Decision Tree)\nรอบที่ t เพื่อทำนาย 5 ท่าทาง", fontsize=10.5)
    draw_rect(ax, cx, y_5, rw, rh, "คำนวณค่าความผิดพลาด\n(Residual / Gradient)", fontsize=10.5)
    draw_rect(ax, cx, y_6, rw, rh, "อัปเดตคะแนนสะสมของโมเดล\n(คูณ Learning Rate = 0.06)", fontsize=10.5)

    dw, dh = 3.5, 1.85
    draw_diamond(ax, cx, y_dec, dw, dh, "เทรนครบ\n250 รอบ\nหรือไม่?", fontsize=10.5)

    draw_rect(ax, cx, y_7, rw, rh, "รวมคะแนนทุกต้นและแปลงเป็น % (Softmax)\nและบันทึกโมเดล multipose_model.pkl", fontsize=10.2)
    draw_oval(ax, cx, y_end, 2.7, 0.85, "สิ้นสุด", fontsize=11.5)

    # Vertical arrows
    draw_arrow(ax, cx, y_start - 0.425, cx, y_1 + rh / 2)
    draw_arrow(ax, cx, y_1 - rh / 2, cx, y_2 + rh / 2)
    draw_arrow(ax, cx, y_2 - rh / 2, cx, y_3 + rh / 2)
    draw_arrow(ax, cx, y_3 - rh / 2, cx, y_4 + rh / 2)
    draw_arrow(ax, cx, y_4 - rh / 2, cx, y_5 + rh / 2)
    draw_arrow(ax, cx, y_5 - rh / 2, cx, y_6 + rh / 2)
    draw_arrow(ax, cx, y_6 - rh / 2, cx, y_dec + dh / 2)
    draw_arrow(ax, cx, y_dec - dh / 2, cx, y_7 + rh / 2)
    draw_arrow(ax, cx, y_7 - rh / 2, cx, y_end + 0.425)

    # Yes label
    ax.text(cx + 0.35, y_dec - dh / 2 - 0.22, "ใช่", ha="left", va="center", fontsize=11, color=TEXT_COLOR)

    # Loop-back arrow ("ไม่") on the right — matching reference flowchart style
    loop_x = 3.85
    draw_ortho_arrow(ax, [
        (cx + dw / 2, y_dec),
        (loop_x, y_dec),
        (loop_x, y_4),
        (cx + rw / 2, y_4),
    ])
    ax.text(loop_x + 0.28, (y_dec + y_4) / 2, "ไม่\n(เพิ่มรอบ t+1)", ha="left", va="center", fontsize=10.5, color=TEXT_COLOR, linespacing=1.3)

    fig.savefig(out_path, dpi=300, bbox_inches="tight", pad_inches=0.25, facecolor=FILL_COLOR)
    plt.close(fig)
    print(f"Saved: {out_path}")


def generate_decision_tree_flowchart(out_path):
    """แผนภาพโครงสร้าง Decision Tree 1 ต้น (ดึงค่าจริงจากต้นที่ 1 คลาส Fall ใน multipose_model.pkl)."""
    fig, ax = _setup_axes(figsize=(19.0, 11.4), xlim=(-12.0, 13.0), ylim=(-0.6, 11.4))

    # Y levels
    y_start = 10.75
    y_root = 8.95
    y_l1 = 6.60
    y_l2 = 4.20
    y_l3 = 1.85
    y_l4 = 0.15

    # Start oval
    draw_oval(ax, 0.0, y_start, 3.8, 0.85, "เริ่มต้น (ข้อมูล 1 เฟรม)", fontsize=11)

    # Level 0: Root Decision
    draw_diamond(ax, 0.0, y_root, 4.3, 1.85, "สัดส่วน กว้าง/สูง\n<= 1.37 ?", fontsize=10.5)
    draw_arrow(ax, 0.0, y_start - 0.425, 0.0, y_root + 0.925)

    # Level 1: Left & Right
    lx1, rx1 = -5.6, 5.8
    draw_diamond(ax, lx1, y_l1, 3.9, 1.75, "มุมต้นขา\n<= 24 องศา ?", fontsize=10.2)
    draw_diamond(ax, rx1, y_l1, 3.9, 1.75, "มุมต้นขา\n<= 0 องศา ?", fontsize=10.2)

    # Root -> Level 1 orthogonal arrows
    draw_ortho_arrow(ax, [(-2.15, y_root), (lx1, y_root), (lx1, y_l1 + 0.875)])
    ax.text((-2.15 + lx1) / 2, y_root + 0.22, "ใช่ (ตัวตั้ง/แคบ)", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    draw_ortho_arrow(ax, [(2.15, y_root), (rx1, y_root), (rx1, y_l1 + 0.875)])
    ax.text((2.15 + rx1) / 2, y_root + 0.22, "ไม่ (ตัวนอนกว้าง)", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    # Level 2 Left-Left & Left-Right
    x_ll = -8.0
    x_lr = -2.4
    draw_diamond(ax, x_ll, y_l2, 3.6, 1.70, "ไหล่อยู่ต่ำกว่า\nสะโพก ?", fontsize=10)
    draw_rect(ax, x_lr, y_l2, 3.3, 1.05, "ตรวจจุดข้อต่อย่อยต่อ\n(เช่น ตำแหน่งตา/สะโพก)", fontsize=9.8)

    draw_ortho_arrow(ax, [(lx1 - 1.95, y_l1), (x_ll, y_l1), (x_ll, y_l2 + 0.85)])
    ax.text((lx1 - 1.95 + x_ll) / 2, y_l1 + 0.20, "ใช่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    draw_ortho_arrow(ax, [(lx1 + 1.95, y_l1), (x_lr, y_l1), (x_lr, y_l2 + 0.525)])
    ax.text((lx1 + 1.95 + x_lr) / 2, y_l1 + 0.20, "ไม่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    # Level 2 Right-Left & Right-Right
    x_rl = 2.6
    x_rr = 9.5
    draw_diamond(ax, x_rl, y_l2, 3.6, 1.70, "มุมลำตัว\n<= 66 องศา ?", fontsize=10)
    draw_diamond(ax, x_rr, y_l2, 3.7, 1.70, "มุมลำตัว\n<= 65.5 องศา ?", fontsize=10)

    draw_ortho_arrow(ax, [(rx1 - 1.95, y_l1), (x_rl, y_l1), (x_rl, y_l2 + 0.85)])
    ax.text((rx1 - 1.95 + x_rl) / 2, y_l1 + 0.20, "ใช่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    draw_ortho_arrow(ax, [(rx1 + 1.95, y_l1), (x_rr, y_l1), (x_rr, y_l2 + 0.85)])
    ax.text((rx1 + 1.95 + x_rr) / 2, y_l1 + 0.20, "ไม่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    # Level 3 under x_ll (Left-Left): arrows go cleanly OUTWARD from diamond tips
    x_lll = -10.2
    x_llr = -5.5
    draw_rect(ax, x_lll, y_l3, 2.6, 1.05, "Leaf: +0.260\n(มีโอกาสล้ม)", fontsize=9.8)
    draw_diamond(ax, x_llr, y_l3, 3.5, 1.65, "มุมลำตัว\n<= 49 องศา ?", fontsize=9.8)

    draw_ortho_arrow(ax, [(x_ll - 1.8, y_l2), (x_lll, y_l2), (x_lll, y_l3 + 0.525)])
    ax.text((x_ll - 1.8 + x_lll) / 2, y_l2 + 0.20, "ใช่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    draw_ortho_arrow(ax, [(x_ll + 1.8, y_l2), (x_llr, y_l2), (x_llr, y_l3 + 0.825)])
    ax.text((x_ll + 1.8 + x_llr) / 2, y_l2 + 0.20, "ไม่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    # Level 4 under x_llr: arrows go cleanly OUTWARD
    x_llrl = -7.8
    x_llrr = -3.2
    draw_rect(ax, x_llrl, y_l4, 2.7, 0.98, "Leaf: -0.069\n(ไม่ล้ม)", fontsize=9.8)
    draw_rect(ax, x_llrr, y_l4, 2.7, 0.98, "Leaf: +0.147\n(อาจล้ม)", fontsize=9.8)

    draw_ortho_arrow(ax, [(x_llr - 1.75, y_l3), (x_llrl, y_l3), (x_llrl, y_l4 + 0.49)])
    ax.text((x_llr - 1.75 + x_llrl) / 2, y_l3 + 0.18, "ใช่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    draw_ortho_arrow(ax, [(x_llr + 1.75, y_l3), (x_llrr, y_l3), (x_llrr, y_l4 + 0.49)])
    ax.text((x_llr + 1.75 + x_llrr) / 2, y_l3 + 0.18, "ไม่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    # Level 3 under x_rl (Right-Left): arrows go cleanly OUTWARD
    x_rll = 0.2
    x_rlr = 4.6
    draw_rect(ax, x_rll, y_l3, 2.55, 1.05, "Leaf: -0.055\n(ไม่ล้ม)", fontsize=9.8)
    draw_rect(ax, x_rlr, y_l3, 2.55, 1.05, "Leaf: +0.120\n(มีโอกาสล้ม)", fontsize=9.8)

    draw_ortho_arrow(ax, [(x_rl - 1.8, y_l2), (x_rll, y_l2), (x_rll, y_l3 + 0.525)])
    ax.text((x_rl - 1.8 + x_rll) / 2, y_l2 + 0.20, "ใช่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    draw_ortho_arrow(ax, [(x_rl + 1.8, y_l2), (x_rlr, y_l2), (x_rlr, y_l3 + 0.525)])
    ax.text((x_rl + 1.8 + x_rlr) / 2, y_l2 + 0.20, "ไม่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    # Level 3 under x_rr (Right-Right): arrows go cleanly OUTWARD
    x_rrl = 7.45
    x_rrr = 11.45
    draw_rect(ax, x_rrl, y_l3, 2.55, 1.05, "Leaf: +0.222\n(แนวโน้มล้ม)", fontsize=9.8)
    draw_rect(ax, x_rrr, y_l3, 2.55, 1.05, "Leaf: +0.284\n(ล้มชัดเจน)", fontsize=9.8)

    draw_ortho_arrow(ax, [(x_rr - 1.85, y_l2), (x_rrl, y_l2), (x_rrl, y_l3 + 0.525)])
    ax.text((x_rr - 1.85 + x_rrl) / 2, y_l2 + 0.20, "ใช่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    draw_ortho_arrow(ax, [(x_rr + 1.85, y_l2), (x_rrr, y_l2), (x_rrr, y_l3 + 0.525)])
    ax.text((x_rr + 1.85 + x_rrr) / 2, y_l2 + 0.20, "ไม่", ha="center", va="bottom", fontsize=10, color=TEXT_COLOR)

    fig.savefig(out_path, dpi=300, bbox_inches="tight", pad_inches=0.25, facecolor=FILL_COLOR)
    plt.close(fig)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "training_plots")
    os.makedirs(out_dir, exist_ok=True)
    generate_training_flowchart(os.path.join(out_dir, "flowchart_training_algorithm.png"))
    generate_decision_tree_flowchart(os.path.join(out_dir, "flowchart_decision_tree_fall.png"))
