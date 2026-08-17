"""
Stream Processor Configuration Macros
All CLI flags and their defaults centralized here for easy adjustment.
"""

# Video Processing
DEFAULT_FPS = 5
DEFAULT_LOOP_VIDEO = True  # Set to False to disable video looping

# Drone Metadata (defaults)
DEFAULT_DRONE_ID = "DRN-001"
DEFAULT_DRONE_NAME = "Alpha-1"
DEFAULT_ZONE = "Live Stream Zone"
DEFAULT_LATITUDE = 28.6139
DEFAULT_LONGITUDE = 77.2090
DEFAULT_ALTITUDE = 100.0

# Backend API
API_HOST = "127.0.0.1"
API_PORT = 8000
API_UPDATE_ENDPOINT = f"http://{API_HOST}:{API_PORT}/api/density/update"

# Stream Quality
# Frames are downscaled to this width (aspect ratio preserved) before being
# handed to any detector — bounds per-frame CPU cost and keeps the input
# resolution identical across detectors (sdnet, yolo, ...) for fair benchmarking.
DETECTION_MAX_WIDTH = 480  # matches SDNet's existing proven working size

# CPU thread cap for PyTorch/OpenCV. Without this, a single inference call
# claims every logical core on the machine (PyTorch/OpenCV both default to
# using all cores for one process) — this is what actually causes "CPU usage
# spikes very heavily" with just one drone running. Override with --threads.
DEFAULT_NUM_THREADS = 2

# Detection Tuning
MIN_CONFIDENCE = 0.5  # Minimum confidence for detections
MAX_DETECTIONS = 1000  # Cap on points per frame

# ---------------------------------------------------------------------------
# Model presets — the list of selectable `--model <key>` values.
# ---------------------------------------------------------------------------
# Add a new pretrained model by adding an entry here — no changes needed in
# detection.py or stream_processor.py. Each entry:
#   detector       - which detector *implementation* backs it (see
#                    detection.py's _DETECTOR_CLASSES; only add a new one of
#                    these when the model needs genuinely new inference code,
#                    not for a same-architecture model with different weights)
#   weights        - default weights path (relative to cv_pipeline/), or None
#                    to auto-discover (sdnet: first *.pth in crowd_models/).
#                    Always overridable via --model-path.
#   label          - human-readable description, shown in --help and usable
#                    by any future admin-UI model picker.
#   person_classes - (yolo only) which of the model's output classes count as
#                    a person. COCO has a single `person` class; VisDrone
#                    splits standing/walking `pedestrian` from `people` in
#                    other postures, so both must be counted.
MODEL_PRESETS = {
    "sdnet": {
        "detector": "sdnet",
        "weights": None,
        "label": "SDNet (MovingDroneCrowd, temporal density map)",
    },
    "yolo": {
        "detector": "yolo",
        "weights": "yolov8n.pt",
        "person_classes": [0],
        "label": "YOLOv8n (COCO) — general-purpose, ground-level photos",
    },
    "yolo-visdrone": {
        "detector": "yolo",
        "weights": "weights/yolov8n-visdrone.pt",
        "person_classes": [0, 1],
        "label": "YOLOv8n (VisDrone) — aerial/drone-camera pretrained",
    },
}

# Logging
VERBOSE = False  # Set to False for silent mode
PRINT_INTERVAL = 10  # Print stats every N frames

# Live Stream Reconnection (applies when source is a URL, e.g. rtsp://)
# Seconds to wait between reconnection attempts (doubles each attempt up to MAX_RECONNECT_DELAY_SECONDS)
RECONNECT_DELAY_SECONDS = 3
MAX_RECONNECT_DELAY_SECONDS = 30
# 0 = retry indefinitely; set to a positive integer to cap attempts before giving up
MAX_RECONNECT_ATTEMPTS = 0

# URL schemes that indicate a live network stream (not a local file)
LIVE_URL_SCHEMES = {"rtsp", "rtsps", "rtmp", "rtmps", "http", "https"}
