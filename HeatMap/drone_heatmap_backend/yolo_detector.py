"""
YOLO Detector: optional person detector based on Ultralytics YOLO.
"""

from typing import List, Tuple
import os
import cv2
import numpy as np


class YOLODetector:
    def __init__(self, weights_path: str = "yolov8n.pt", device: str = None, confidence: float = 0.35):
        # PyTorch 2.6 changed torch.load default to weights_only=True.
        # For trusted local YOLO checkpoints, force the old behavior.
        os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

        try:
            from ultralytics import YOLO
            from ultralytics.nn.tasks import DetectionModel
        except ImportError as e:
            raise ImportError(
                "Ultralytics YOLO is required for YOLODetector. Install with `pip install ultralytics`."
            ) from e

        # PyTorch 2.6+ loads checkpoints with weights_only=True by default.
        # Allowlist Ultralytics DetectionModel so trusted local YOLO checkpoints can load.
        try:
            import torch
            if hasattr(torch.serialization, "add_safe_globals"):
                torch.serialization.add_safe_globals([DetectionModel])
        except Exception:
            pass

        self.model = YOLO(weights_path)
        if device:
            try:
                self.model.to(device)
            except Exception:
                pass
        self.confidence = confidence

    def detect_people(self, frame: np.ndarray) -> Tuple[List[Tuple[int, int]], float]:
        # Inference returns a Results object with boxes and classes
        results = self.model(frame, conf=self.confidence, classes=[0])
        points = []
        total = 0

        for res in results:
            boxes = getattr(res, 'boxes', [])
            for box in boxes:
                # YOLO box is [x1, y1, x2, y2]
                xyxy = box.xyxy.cpu().numpy().astype(np.float32).reshape(-1)
                if len(xyxy) >= 4:
                    x1, y1, x2, y2 = xyxy[:4]
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)
                    points.append((cx, cy))
                    total += 1

        return points, float(total)

    def reset(self):
        # No internal state for YOLO currently.
        return
