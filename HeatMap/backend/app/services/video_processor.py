"""
Video Processor Service
Handles RTSP video stream ingestion and frame-level person detection.
"""

from app.config import settings
import cv2


class VideoProcessor:
    def __init__(
        self,
        rtsp_url: str,
        model_type: str = "yolo",
        model_path: str = None,
        device: str = None,
        confidence: float = settings.CONFIDENCE_THRESHOLD,
    ):
        self.rtsp_url = rtsp_url
        self.model_type = model_type
        self.model_path = model_path
        self.device = device
        self.confidence = confidence
        self.capture = None
        self.detector = None

    async def initialize(self):
        """Initialize detector and video capture."""
        # Lazy import to avoid heavy dependency if unused
        if self.model_type == "yolo":
            try:
                from ultralytics import YOLO
            except ImportError as e:
                raise ImportError("Install ultralytics to use YOLO model: pip install ultralytics") from e

            self.detector = YOLO(self.model_path or settings.YOLO_MODEL)
            if self.device:
                try:
                    self.detector.to(self.device)
                except Exception:
                    pass

        elif self.model_type == "sdnet":
            try:
                from drone_heatmap_backend.sdnet_detector import SDNetDetector
            except ImportError as e:
                raise ImportError("SDNet detector requires drone_heatmap_backend module and dependencies.") from e
            self.detector = SDNetDetector(weights_path=self.model_path, device=self.device)

        else:
            raise ValueError(f"Unsupported model_type: {self.model_type}")

        self.capture = cv2.VideoCapture(self.rtsp_url)
        if not self.capture.isOpened():
            raise RuntimeError(f"Unable to open RTSP source: {self.rtsp_url}")

    async def process_frame(self, frame):
        """Detect persons in a single frame and return “points” and headcount."""
        if self.detector is None:
            raise RuntimeError("Detector not initialized")

        if self.model_type == "yolo":
            results = self.detector(frame, conf=self.confidence, classes=[0])
            points = []
            for res in results:
                for box in getattr(res, "boxes", []):
                    xyxy = box.xyxy.cpu().numpy().reshape(-1)
                    if len(xyxy) >= 4:
                        x1, y1, x2, y2 = xyxy[:4]
                        points.append((int((x1 + x2) / 2), int((y1 + y2) / 2)))
            return points
        else:
            points, headcount = self.detector.detect_people(frame)
            return points

    async def get_frame(self):
        if self.capture is None:
            raise RuntimeError("Capture not initialized")
        ret, frame = self.capture.read()
        return frame if ret else None

    async def release(self):
        if self.capture is not None:
            self.capture.release()
        if self.detector is not None and hasattr(self.detector, "reset"):
            self.detector.reset()

