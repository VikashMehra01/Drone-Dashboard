"""
Detection module - uses SDNet density map estimation for accurate crowd counting.
"""
import cv2
from typing import List, Tuple
from sdnet_detector import SDNetDetector
from yolo_detector import YOLODetector
import cv2
import os

# Supported backends for crowd density estimation
_DETECTOR_REGISTRY = {
    "sdnet": SDNetDetector,
    "yolo": YOLODetector,
}


class PersonDetector:
    def __init__(
        self,
        model_type: str = "sdnet",
        model_path: str = None,
        device: str = None,
        confidence: float = 0.35,
        **kwargs,
    ):
        """Select a detection algorithm and initialize it.

        Args:
            model_type: One of 'sdnet', 'yolo', or future models.
            model_path: Path to model weights (if required).
            device: 'cuda' or 'cpu'.
            confidence: Confidence threshold for detectors (used by YOLO).
        """
        detector_key = (model_type or "sdnet").strip().lower()
        detector_cls = _DETECTOR_REGISTRY.get(detector_key)
        if detector_cls is None:
            raise ValueError(f"Unsupported detector type '{model_type}'. Supported: {list(_DETECTOR_REGISTRY.keys())}")

        if detector_key == "sdnet":
            # SDNet expects a .pth weights file.
            if model_path is None:
                mdc_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'MovingDroneCrowd')
                for f in os.listdir(mdc_root):
                    if f.endswith('.pth'):
                        model_path = os.path.join(mdc_root, f)
                        break
                if model_path is None:
                    raise FileNotFoundError("Could not find SDNet .pth weights in MovingDroneCrowd folder.")
            self.detector = detector_cls(weights_path=model_path, device=device)
        elif detector_key == "yolo":
            self.detector = detector_cls(weights_path=model_path or "yolov8n.pt", device=device, confidence=confidence)
        else:
            self.detector = detector_cls(**kwargs)

    def detect_people(self, frame: cv2.typing.MatLike) -> Tuple[List[Tuple[int, int]], float]:
        """Returns points and count from the chosen model."""
        result = self.detector.detect_people(frame)
        return result

    def reset(self):
        """Reset internal model state (optional)."""
        if hasattr(self.detector, "reset"):
            self.detector.reset()

