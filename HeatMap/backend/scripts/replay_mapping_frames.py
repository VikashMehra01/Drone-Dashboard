"""
Offline mapping replay - feeds a local folder of DJI frame images through
POST /api/mapping/feed-image, one by one, to sanity-check the orthomosaic
pipeline (pose extraction -> stitching) end-to-end against a running
HeatMap backend.

Each image must carry DJI XMP GPS/gimbal metadata (the same requirement
as SkyForge GCS's live feed) - PoseExtractor reads GpsLatitude,
GpsLongitude, RelativeAltitude, and the three GimbalXDegree fields.

Usage:
    python scripts/replay_mapping_frames.py --dir /path/to/frames
    python scripts/replay_mapping_frames.py --dir /path/to/frames --fps 2 --reset
"""

import argparse
import time
from pathlib import Path

import requests

DEFAULT_API_URL = "http://127.0.0.1:8000/api/mapping"
IMAGE_EXTENSIONS = {".jpg", ".jpeg"}  # DJI XMP metadata lives in JPEG only


def replay(frames_dir: str, api_url: str, fps: float, reset_first: bool):
    folder = Path(frames_dir)
    if not folder.is_dir():
        print(f"Error: not a directory: {folder}")
        return

    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    if not files:
        print(f"No .jpg/.jpeg frames found in {folder}")
        return

    print(f"[Replay] Found {len(files)} frames in {folder}")

    if reset_first:
        try:
            requests.post(f"{api_url}/reset", timeout=5)
            print("[Replay] Mapper reset.")
        except requests.exceptions.RequestException as e:
            print(f"[Replay] Reset failed (continuing anyway): {e}")

    delay = 1.0 / fps if fps > 0 else 0.0
    fed, skipped, errored = 0, 0, 0

    for i, path in enumerate(files, start=1):
        start = time.time()
        with open(path, "rb") as f:
            files_payload = {"file": (path.name, f, "image/jpeg")}
            try:
                resp = requests.post(f"{api_url}/feed-image", files=files_payload, timeout=30)
                resp.raise_for_status()
                result = resp.json()
                status = result.get("status", "unknown")
                if status == "success":
                    fed += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    errored += 1
                print(f"[{i}/{len(files)}] {path.name}: {status} - {result.get('message', '')}")
            except requests.exceptions.RequestException as e:
                errored += 1
                print(f"[{i}/{len(files)}] {path.name}: request failed - {e}")

        elapsed = time.time() - start
        sleep_time = delay - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    print(f"\n[Replay] Done. fed={fed} skipped={skipped} errored={errored}")
    print(f"[Replay] View the stitched map at: {api_url}/latest")
    print(f"[Replay] Coverage/QA data at:      {api_url}/coverage")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Replay a local folder of DJI frames through the mapping pipeline."
    )
    parser.add_argument("--dir", type=str, required=True, help="Folder of .jpg frames")
    parser.add_argument("--api-url", type=str, default=DEFAULT_API_URL,
                         help=f"Mapping API base URL (default: {DEFAULT_API_URL})")
    parser.add_argument("--fps", type=float, default=2.0,
                         help="Target replay rate, frames/sec (default: 2). Use 0 for no throttling.")
    parser.add_argument("--reset", action="store_true",
                         help="Reset the mapper before replaying (clears any previous session).")

    args = parser.parse_args()
    replay(args.dir, args.api_url, args.fps, args.reset)
