import cv2
import time
import requests
import argparse
from urllib.parse import urlparse
from detection import PersonDetector
from stream_config import (
    API_UPDATE_ENDPOINT,
    DEFAULT_FPS,
    DEFAULT_LOOP_VIDEO,
    LIVE_URL_SCHEMES,
    RECONNECT_DELAY_SECONDS,
    MAX_RECONNECT_DELAY_SECONDS,
    MAX_RECONNECT_ATTEMPTS,
)

# FastAPI endpoint for updating live density
API_UPDATE_URL = API_UPDATE_ENDPOINT


def is_live_url(source: str) -> bool:
    """
    Returns True if *source* is a network stream URL (RTSP, RTMP, HTTP, etc.)
    rather than a local video file path.
    """
    try:
        parsed = urlparse(source)
        return parsed.scheme.lower() in LIVE_URL_SCHEMES
    except Exception:
        return False


def process_stream(
    source: str,
    target_fps: int = 5,
    drone_id: str | None = None,
    drone_name: str | None = None,
    zone: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    altitude: float | None = None,
    loop_video: bool | None = None,
    model_type: str = "sdnet",
    model_path: str | None = None,
    device: str | None = None,
    yolo_confidence: float = 0.35,
    max_reconnect_attempts: int = MAX_RECONNECT_ATTEMPTS,
):
    """
    Process a video source (local file OR live network stream URL) at a given FPS,
    estimate crowd density, and post the data to the backend.

    Live URL behaviour:
      - Auto-reconnects with exponential backoff when the stream drops.
      - loop_video is ignored (always False) for live URLs.
      - max_reconnect_attempts = 0 means retry indefinitely.
    """
    live = is_live_url(source)

    # For live streams, looping is meaningless — disable it.
    # For local files, fall back to the configured default if caller didn't specify.
    if loop_video is None:
        loop_video = False if live else DEFAULT_LOOP_VIDEO

    if live:
        print(f"[StreamProcessor] Detected live URL: {source}")
        print(f"[StreamProcessor] Auto-reconnect enabled (max attempts: {'∞' if max_reconnect_attempts == 0 else max_reconnect_attempts})")
    else:
        print(f"[StreamProcessor] Local file source: {source}  loop={loop_video}")

    print(f"[StreamProcessor] Target FPS: {target_fps}  Model: {model_type}")

    detector = PersonDetector(
        model_type=model_type,
        model_path=model_path,
        device=device,
        confidence=yolo_confidence,
    )

    loop_delay = 1.0 / target_fps
    frame_count = 0
    reconnect_count = 0
    reconnect_delay = RECONNECT_DELAY_SECONDS

    try:
        while True:
            # ── Open / re-open the source ────────────────────────────────
            if live and reconnect_count > 0:
                print(f"[StreamProcessor] Reconnecting to {source} "
                      f"(attempt {reconnect_count}, delay {reconnect_delay}s)…")
                time.sleep(reconnect_delay)

            cap = cv2.VideoCapture(source)

            if not cap.isOpened():
                if not live:
                    print(f"[StreamProcessor] Error: could not open source: {source}")
                    return

                # Live stream: schedule a retry
                reconnect_count += 1
                if max_reconnect_attempts > 0 and reconnect_count > max_reconnect_attempts:
                    print(f"[StreamProcessor] Max reconnect attempts ({max_reconnect_attempts}) reached. Stopping.")
                    return

                # Exponential backoff, capped at MAX_RECONNECT_DELAY_SECONDS
                reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY_SECONDS)
                print(f"[StreamProcessor] Could not open stream. Next retry in {reconnect_delay}s…")
                continue

            # Successfully opened — reset reconnect state
            reconnect_count = 0
            reconnect_delay = RECONNECT_DELAY_SECONDS
            print(f"[StreamProcessor] Stream opened successfully.")

            # ── Frame processing loop ────────────────────────────────────
            stream_active = True
            while stream_active:
                start_time = time.time()
                ret, frame = cap.read()

                if not ret:
                    # ── End-of-stream / network drop ─────────────────────
                    if live:
                        print("[StreamProcessor] Stream interrupted. Will reconnect…")
                        cap.release()
                        reconnect_count += 1
                        if max_reconnect_attempts > 0 and reconnect_count > max_reconnect_attempts:
                            print(f"[StreamProcessor] Max reconnect attempts reached. Stopping.")
                            return
                        reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY_SECONDS)
                        stream_active = False  # break inner loop → outer loop reconnects
                        continue
                    elif loop_video:
                        print("[StreamProcessor] End of file. Looping…")
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        print("[StreamProcessor] End of file. Stopping.")
                        cap.release()
                        return

                frame_count += 1

                # ── Detect people ────────────────────────────────────────
                points, headcount = detector.detect_people(frame)

                payload = {
                    "headcount": float(headcount),
                    "timestamp": time.time(),
                    "points_count": len(points),
                    "source": source,
                    "drone_id": drone_id,
                    "drone_name": drone_name,
                    "zone": zone,
                    "latitude": latitude,
                    "longitude": longitude,
                    "altitude": altitude,
                    "loop_video": loop_video,
                }

                # ── POST to backend ──────────────────────────────────────
                try:
                    response = requests.post(API_UPDATE_URL, json=payload, timeout=2)
                    print(f"Frame {frame_count}: Headcount {headcount:.1f} -> {response.status_code}")
                except requests.exceptions.RequestException as e:
                    print(f"Frame {frame_count}: Headcount {headcount:.1f} -> Backend unavailable ({e})")

                # ── Enforce target FPS ───────────────────────────────────
                elapsed = time.time() - start_time
                sleep_time = loop_delay - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

            # End of inner frame loop (only reached when stream_active=False for live URLs)
            if not live:
                break   # local file finished — exit outer loop too

    except KeyboardInterrupt:
        print("\n[StreamProcessor] Stopped by user.")
    finally:
        if cap.isOpened():
            cap.release()
        print("[StreamProcessor] Released video capture.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Live Stream Density Processor — supports local files AND live URLs (RTSP, RTMP, HTTP)"
    )
    parser.add_argument(
        "--source",
        type=str,
        default="../video-stream/sample_crowd.mp4",
        help=(
            "Path to a local video file OR a live stream URL. "
            "Examples:\n"
            "  Local file : ../media/videos/droneVid.mp4\n"
            "  RTSP       : rtsp://192.168.1.10:554/drone1\n"
            "  HTTP MJPEG : http://192.168.1.10:8080/video\n"
            "  RTMP       : rtmp://live.example.com/live/stream-key"
        ),
    )
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS,
                        help="Target processing frames per second (default: 5)")
    parser.add_argument("--drone-id", type=str, default=None,
                        help="Optional drone ID (e.g., DRN-001)")
    parser.add_argument("--drone-name", type=str, default=None,
                        help="Optional drone display name")
    parser.add_argument("--zone", type=str, default=None,
                        help="Optional zone name")
    parser.add_argument("--latitude", type=float, default=None,
                        help="Drone GPS latitude")
    parser.add_argument("--longitude", type=float, default=None,
                        help="Drone GPS longitude")
    parser.add_argument("--altitude", type=float, default=None,
                        help="Drone altitude in metres")
    parser.add_argument(
        "--loop",
        type=lambda v: v.lower() not in ("false", "0", "no"),
        default=None,
        metavar="true|false",
        help=(
            "Loop local video files on end (default: true for files, always false for live URLs). "
            "Ignored when source is a live URL."
        ),
    )
    parser.add_argument("--model", type=str, default="sdnet", choices=["sdnet", "yolo"],
                        help="Detector type (default: sdnet)")
    parser.add_argument("--model-path", type=str, default=None,
                        help="Optional path to model weights")
    parser.add_argument("--device", type=str, default=None,
                        help="Compute device: cuda or cpu")
    parser.add_argument("--yolo-confidence", type=float, default=0.35,
                        help="YOLO confidence threshold (default: 0.35)")
    parser.add_argument(
        "--max-reconnect-attempts",
        type=int,
        default=MAX_RECONNECT_ATTEMPTS,
        help=(
            "Max reconnect attempts for live streams (0 = infinite, default: 0). "
            "Ignored for local files."
        ),
    )

    args = parser.parse_args()

    process_stream(
        source=args.source,
        target_fps=args.fps,
        drone_id=args.drone_id,
        drone_name=args.drone_name,
        zone=args.zone,
        latitude=args.latitude,
        longitude=args.longitude,
        altitude=args.altitude,
        loop_video=args.loop,
        model_type=args.model,
        model_path=args.model_path,
        device=args.device,
        yolo_confidence=args.yolo_confidence,
        max_reconnect_attempts=args.max_reconnect_attempts,
    )
