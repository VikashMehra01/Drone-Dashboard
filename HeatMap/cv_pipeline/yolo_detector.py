"""
YOLO Detector: optional person detector based on Ultralytics YOLO.
"""

from typing import List, Tuple
import os
import cv2
import numpy as np

from stream_config import DETECTION_MAX_WIDTH


class YOLODetector:
    def __init__(self, weights_path: str = "yolov8n.pt", device: str = None, confidence: float = 0.35,
                 person_classes: list[int] | None = None):
        # Which output class indices count as "a person" — model-specific.
        # COCO has a single `person` class (0); VisDrone splits `pedestrian`
        # (0) from `people` in other postures (1), both need counting.
        # Defaults to COCO's [0] for backward compatibility.
        self.person_classes = person_classes if person_classes is not None else [0]
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
        # Downscale before inference (aspect ratio preserved) — bounds CPU cost
        # and keeps the input resolution consistent with the SDNet path, for
        # fair model-vs-model comparisons. Only the point *count*, not these
        # pixel coordinates, ever crosses the wire to the backend, so operating
        # in downscaled coordinate space here is safe.
        h, w = frame.shape[:2]
        if w > DETECTION_MAX_WIDTH:
            target_h = int(h * (DETECTION_MAX_WIDTH / w))
            frame = cv2.resize(frame, (DETECTION_MAX_WIDTH, target_h))

        # Inference returns a Results object with boxes and classes
        results = self.model(frame, conf=self.confidence, classes=self.person_classes)
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
