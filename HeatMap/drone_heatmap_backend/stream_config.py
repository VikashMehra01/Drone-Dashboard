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
FRAME_DOWNSCALE = 0.5  # Reduce frame size to 50% for faster processing
TARGET_WIDTH = 640  # Target width after downscaling
TARGET_HEIGHT = 480  # Target height after downscaling

# Detection Tuning
MIN_CONFIDENCE = 0.5  # Minimum confidence for detections
MAX_DETECTIONS = 1000  # Cap on points per frame

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
