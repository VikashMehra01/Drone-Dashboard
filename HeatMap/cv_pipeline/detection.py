"""
Detection module - dispatches to whichever detector implements the chosen
--model preset (see stream_config.MODEL_PRESETS for the list of models).
"""
import cv2
from typing import List, Tuple
import os

from sdnet_detector import SDNetDetector
from yolo_detector import YOLODetector
from stream_config import MODEL_PRESETS

# Maps each preset's "detector" field (stream_config.MODEL_PRESETS) to the
# Python class that implements it. Only add an entry here when a model needs
# genuinely new inference code — a same-architecture model with different
# weights (e.g. a new YOLO checkpoint) is just a new MODEL_PRESETS entry.
_DETECTOR_CLASSES = {
    "sdnet": SDNetDetector,
    "yolo": YOLODetector,
}


def _find_sdnet_weights() -> str:
    mdc_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'crowd_models')
    for f in os.listdir(mdc_root):
        if f.endswith('.pth'):
            return os.path.join(mdc_root, f)
    raise FileNotFoundError("Could not find SDNet .pth weights in crowd_models/ folder.")


class PersonDetector:
    def __init__(
        self,
        model_type: str = "sdnet",
        model_path: str = None,
        device: str = None,
        confidence: float = 0.35,
        **kwargs,
    ):
        """Select a detection model (see stream_config.MODEL_PRESETS) and initialize it.

        Args:
            model_type: A key from stream_config.MODEL_PRESETS (e.g. 'sdnet', 'yolo', 'yolo-visdrone').
            model_path: Path to model weights, overriding the preset's default.
            device: 'cuda' or 'cpu'.
            confidence: Confidence threshold for detectors (used by YOLO-based presets).
        """
        preset_key = (model_type or "sdnet").strip().lower()
        preset = MODEL_PRESETS.get(preset_key)
        if preset is None:
            raise ValueError(f"Unsupported model '{model_type}'. Supported: {list(MODEL_PRESETS.keys())}")

        detector_cls = _DETECTOR_CLASSES.get(preset["detector"])
        if detector_cls is None:
            raise ValueError(f"Model '{preset_key}' references unknown detector implementation '{preset['detector']}'")

        weights = model_path or preset.get("weights")

        if preset["detector"] == "sdnet":
            self.detector = detector_cls(weights_path=weights or _find_sdnet_weights(), device=device)
        elif preset["detector"] == "yolo":
            self.detector = detector_cls(
                weights_path=weights or "yolov8n.pt",
                device=device,
                confidence=confidence,
                person_classes=preset.get("person_classes"),
            )
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

