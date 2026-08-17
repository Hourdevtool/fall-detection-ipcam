"""
frame_splitter.py — Dual Camera Frame Splitter

กล้องบางรุ่น (เช่น FNK-D14Z) มีเลนส์ 2 ตัว ส่งภาพมารวมกันเป็นเฟรมเดียว
(บน/ล่าง หรือ ซ้าย/ขวา) ทำให้ AI เห็นภาพผิดปกติ

Module นี้จะ:
1. Auto-detect ว่าเฟรมเป็น dual camera จาก aspect ratio
2. Split เป็น sub-frames แยกกัน
3. รองรับ manual config override ผ่าน camera_config
"""

import cv2
import numpy as np


class FrameSplitter:
    """Split dual-camera frames into individual sub-frames.

    Supports:
    - Vertical split (top/bottom) — กล้อง 2 ตัวส่งภาพแนวตั้ง
    - Horizontal split (left/right) — กล้อง 2 ตัวส่งภาพแนวนอน
    - Auto-detection from frame aspect ratio
    - Manual config override per camera

    Usage:
        splitter = FrameSplitter(camera_config={"dual": True, "split": "vertical"})
        sub_frames = splitter.split_frame(frame)
        # Returns: [("top", top_half), ("bottom", bottom_half)]
        # Or for single camera: [("full", frame)]
    """

    # Aspect ratio thresholds for auto-detection
    # Normal cameras: 16:9 (h/w=0.5625), 4:3 (h/w=0.75)
    # Dual vertical: two 16:9 stacked (h/w=1.125), two 4:3 stacked (h/w=1.5)
    VERTICAL_THRESHOLD = 1.0    # h/w > 1.0 → likely dual vertical
    HORIZONTAL_THRESHOLD = 2.8  # w/h > 2.8 → likely dual horizontal

    def __init__(self, camera_config=None):
        """Initialize FrameSplitter.

        Args:
            camera_config: dict with optional keys:
                - "dual": bool — force dual camera mode
                - "split": str — "vertical" or "horizontal" (default: "vertical")
                If None or missing "dual" key, auto-detection is used.
        """
        self.camera_config = camera_config or {}
        self._is_dual = self.camera_config.get("dual", None)  # None = auto-detect
        self._split_mode = self.camera_config.get("split", "vertical")
        self._auto_detected = None  # Cache auto-detection result

    def split_frame(self, frame):
        """Split a frame into sub-frames if it's from a dual camera.

        Args:
            frame: BGR image (numpy array)

        Returns:
            List of (label, sub_frame) tuples.
            - Single camera: [("full", frame)]
            - Dual vertical: [("top", top_half), ("bottom", bottom_half)]
            - Dual horizontal: [("left", left_half), ("right", right_half)]
        """
        if frame is None:
            return [("full", frame)]

        # Manual config takes priority
        if self._is_dual is True:
            return self._split(frame, self._split_mode)
        elif self._is_dual is False:
            return [("full", frame)]

        # Auto-detect from aspect ratio (cache result after first detection)
        if self._auto_detected is not None:
            if self._auto_detected == "none":
                return [("full", frame)]
            return self._split(frame, self._auto_detected)

        h, w = frame.shape[:2]
        ratio_hw = h / w if w > 0 else 0

        if ratio_hw > self.VERTICAL_THRESHOLD:
            self._auto_detected = "vertical"
            print(f"[CAM] Auto-detected DUAL camera (vertical split, h/w={ratio_hw:.2f})")
            return self._split(frame, "vertical")
        elif (w / h if h > 0 else 0) > self.HORIZONTAL_THRESHOLD:
            self._auto_detected = "horizontal"
            print(f"[CAM] Auto-detected DUAL camera (horizontal split, w/h={w/h:.2f})")
            return self._split(frame, "horizontal")
        else:
            self._auto_detected = "none"
            return [("full", frame)]

    def _split(self, frame, mode):
        """Split frame into 2 sub-frames.

        Args:
            frame: BGR image
            mode: "vertical" (top/bottom) or "horizontal" (left/right)

        Returns:
            List of (label, sub_frame) tuples
        """
        h, w = frame.shape[:2]

        if mode == "vertical":
            mid = h // 2
            top = frame[:mid, :]
            bottom = frame[mid:, :]
            return [("top", top), ("bottom", bottom)]
        else:  # horizontal
            mid = w // 2
            left = frame[:, :mid]
            right = frame[:, mid:]
            return [("left", left), ("right", right)]

    def is_dual(self):
        """Check if this splitter has detected or been configured as a dual camera.

        Returns:
            True if dual camera, False if single, None if not yet determined
        """
        if self._is_dual is not None:
            return self._is_dual
        if self._auto_detected is not None:
            return self._auto_detected != "none"
        return None
