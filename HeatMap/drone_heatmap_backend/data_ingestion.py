import cv2
import json
from typing import Dict, Any, Tuple, Generator

class VideoIngestor:
    def __init__(self, video_path: str):
        self.video_path = video_path
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise ValueError(f"Could not open video at {video_path}")
            
    def get_frames(self) -> Generator[Tuple[int, cv2.typing.MatLike], None, None]:
        """Yields frame_index, frame."""
        frame_idx = 0
        while True:
            ret, frame = self.cap.read()
            if not ret:
                break
            yield frame_idx, frame
            frame_idx += 1
            
    def get_video_properties(self) -> Dict[str, Any]:
        return {
            "fps": self.cap.get(cv2.CAP_PROP_FPS),
            "width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "frame_count": int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        }

    def close(self):
        self.cap.release()

class MetadataParser:
    def __init__(self, metadata_path: str):
        self.metadata_path = metadata_path
        
    def load_metadata(self) -> Dict[str, Any]:
        """
        Loads metadata (e.g., JSON containing GPS, Altitude, FoV).
        Placeholder implementation.
        """
        # TODO: Implement actual metadata loading based on your data format
        # Expected format:
        # {
        #   "latitude": 37.7749,
        #   "longitude": -122.4194,
        #   "altitude": 50.0, # in meters
        #   "fov_h": 60.0, # Horizontal FoV in degrees
        #   "fov_v": 45.0  # Vertical FoV in degrees
        # }
        with open(self.metadata_path, 'r') as f:
            data = json.load(f)
        return data
