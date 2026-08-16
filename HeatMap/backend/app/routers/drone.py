from fastapi import APIRouter
from app.config import settings
from app.routers.density import current_density_data, active_streams
from pathlib import Path
import time
from urllib.parse import urlparse

router = APIRouter(prefix="/api/drones", tags=["drones"])

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}

# URL schemes that are live network streams (not local file paths)
_LIVE_SCHEMES = {"rtsp", "rtsps", "rtmp", "rtmps", "http", "https"}


def _derive_mediamtx_hls_url(source_url: str) -> str | None:
    """
    Derive the MediaMTX HLS URL from any stream URL that MediaMTX can ingest.

    MediaMTX accepts RTSP, RTSPS, RTMP and RTMPS as inputs and re-publishes
    every stream as an HLS playlist on its built-in HTTP server (default port 8888).
    The stream *path* is the same regardless of the ingest protocol:

        rtsp://localhost:8554/mystream   → http://localhost:8888/mystream/index.m3u8
        rtmp://localhost:1935/live/key   → http://localhost:8888/live/key/index.m3u8
        rtsps://host:8322/cam1          → http://host:8888/cam1/index.m3u8

    Returns None for protocols MediaMTX doesn't ingest (e.g. plain HTTP MJPEG).
    """
    try:
        parsed = urlparse(source_url)
        if parsed.scheme.lower() not in ("rtsp", "rtsps", "rtmp", "rtmps"):
            return None
        host = parsed.hostname or "localhost"
        stream_path = parsed.path.lstrip("/")
        if not stream_path:
            return None
        return f"http://{host}:{settings.MEDIAMTX_HLS_PORT}/{stream_path}/index.m3u8"
    except Exception:
        return None


def _list_video_files() -> list[Path]:
    video_dir = Path(settings.MEDIA_VIDEOS_DIR)
    if not video_dir.exists():
        return []
    return sorted(
        [p for p in video_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS],
        key=lambda p: p.name.lower(),
    )


def _get_active_sources() -> set[str]:
    """Return the video *filenames* of all currently-active file-based streams."""
    active_names = set()
    now = time.time()
    for source, stream_data in active_streams.items():
        ts = stream_data.get("timestamp")
        if ts is None or (now - float(ts)) > settings.STREAM_STALE_SECONDS:
            continue
        parsed = urlparse(source)
        # Only count file-backed sources here
        if parsed.scheme.lower() in _LIVE_SCHEMES:
            continue
        video_name = Path(parsed.path if parsed.scheme else source).name
        active_names.add(video_name)
    return active_names


def _get_stream_data_for_source(source_name: str) -> dict:
    """Get stream data for a specific local video filename."""
    now = time.time()
    for source_url, stream_data in active_streams.items():
        ts = stream_data.get("timestamp")
        if ts is None or (now - float(ts)) > settings.STREAM_STALE_SECONDS:
            continue
        parsed = urlparse(source_url)
        video_name = Path(parsed.path if parsed.scheme else source_url).name
        if video_name == source_name:
            return stream_data
    return None


def _build_url_stream_drones(file_video_names: set[str]) -> list[dict]:
    """
    Build drone cards for active streams whose source is a live URL
    (RTSP, RTMP, HTTP …) rather than a local video file.  These drones
    don't appear in media/videos/ so they must be enumerated separately.
    """
    now = time.time()
    drones = []
    seen_ids: set[str] = set()

    for source_url, stream_data in active_streams.items():
        ts = stream_data.get("timestamp")
        if ts is None or (now - float(ts)) > settings.STREAM_STALE_SECONDS:
            continue

        parsed = urlparse(source_url)
        scheme = parsed.scheme.lower()

        # Only handle live URL sources in this function
        if scheme not in _LIVE_SCHEMES:
            continue

        # Skip if this URL happens to share a filename with a local file
        # (unlikely, but guard against double-counting)
        url_path_name = Path(parsed.path).name
        if url_path_name and url_path_name in file_video_names:
            continue

        drone_id = stream_data.get("drone_id") or f"LIVE-{abs(hash(source_url)) % 10000:04d}"

        # De-duplicate in case the same drone_id appears for multiple source variants
        if drone_id in seen_ids:
            continue
        seen_ids.add(drone_id)

        drones.append(
            {
                "id": drone_id,
                "name": stream_data.get("drone_name") or drone_id,
                "status": "active",
                "latitude": float(stream_data.get("latitude") or 0.0),
                "longitude": float(stream_data.get("longitude") or 0.0),
                "altitude": float(stream_data.get("altitude") or 100.0),
                "battery": 100,
                "peopleCounted": int(stream_data.get("points_count") or 0),
                "headcountDensity": float(stream_data.get("headcount") or 0.0),
                "zone": stream_data.get("zone") or "Live Stream Zone",
                # For URL streams the video_url IS the source URL.
                # The frontend will use this to decide display behaviour.
                "video_url": source_url,
                # hls_url: browser-playable HLS playlist derived via MediaMTX.
                # Set for RTSP, RTSPS, RTMP and RTMPS sources; None otherwise.
                "hls_url": _derive_mediamtx_hls_url(source_url),
                # Expose the raw protocol so the UI can choose the right player
                "stream_protocol": scheme,
            }
        )

    return drones


def _load_all_configs() -> dict[str, dict]:
    """Read all drone configs from the drone_configs DB table. Returns {drone_id: config}."""
    try:
        from app.db import get_db_cursor
        with get_db_cursor(dict_rows=True) as (_, cur):
            cur.execute("SELECT * FROM drone_configs")
            rows = cur.fetchall()
            return {r["drone_id"]: dict(r) for r in rows}
    except Exception as e:
        print(f"[drone] _load_all_configs DB error: {e}")
        return {}


def _build_drones_payload() -> list[dict]:
    files = _list_video_files()
    file_video_names = {v.name for v in files}
    active_source_names = _get_active_sources()

    # Load all saved configs so idle drones use correct name/zone/coords
    saved_configs = _load_all_configs()

    drones: list[dict] = []

    # ── 1. Active file-backed drones ────────────────────────────────────
    for idx, video in enumerate(files):
        is_active = video.name in active_source_names
        if not is_active:
            continue   # skip non-active file drones — handled below via configs

        stream_data = _get_stream_data_for_source(video.name)
        if not stream_data:
            continue

        points = int(stream_data.get("points_count") or 0)
        density = float(stream_data.get("headcount") or 0.0)
        drone_id = stream_data.get("drone_id") or f"DRN-{idx + 1:03d}"
        name = stream_data.get("drone_name") or video.stem
        zone = stream_data.get("zone") or "Live Stream Zone"
        lat = float(stream_data.get("latitude")) if stream_data.get("latitude") is not None else None
        lng = float(stream_data.get("longitude")) if stream_data.get("longitude") is not None else None
        altitude = float(stream_data.get("altitude") or 100)

        drones.append({
            "id": drone_id,
            "name": name,
            "status": "active",
            "latitude": lat,
            "longitude": lng,
            "altitude": altitude,
            "battery": 100,
            "peopleCounted": points,
            "headcountDensity": density,
            "zone": zone,
            "video_url": f"http://localhost:{settings.API_PORT}/videos/{video.name}",
            "stream_protocol": "file",
        })

    # ── 2. Live URL-stream drones ────────────────────────────────────────
    drones.extend(_build_url_stream_drones(file_video_names))

    # ── 3. Saved (stopped) drones from config files ──────────────────────
    # Only include if not already covered above as active
    active_ids = {d["id"] for d in drones}
    for drone_id, cfg in saved_configs.items():
        if drone_id in active_ids:
            continue   # already shown as active
        drones.append({
            "id": drone_id,
            "name": cfg.get("drone_name", drone_id),
            "status": "idle",
            "latitude": cfg.get("latitude"),
            "longitude": cfg.get("longitude"),
            "altitude": cfg.get("altitude"),
            "battery": None,
            "peopleCounted": 0,
            "headcountDensity": 0.0,
            "zone": cfg.get("zone", "Standby"),
            "video_url": cfg.get("source"),
            "stream_protocol": "file",
        })

    return drones


def _is_live_stream_active() -> bool:
    """Check if any stream is currently active."""
    if not active_streams:
        return False

    now = time.time()
    for stream_data in active_streams.values():
        ts = stream_data.get("timestamp")
        if ts and (now - float(ts)) <= settings.STREAM_STALE_SECONDS:
            return True
    return False


@router.get("/")
async def get_drones(include_debug: bool = False):
    """Get drones — active streams, idle saved-config drones, and debug playback."""
    live_active = _is_live_stream_active()
    debug_mode = include_debug or settings.ALLOW_DEBUG_PLAYBACK

    # Always build the full payload (includes stopped/idle drones from saved configs)
    drones = _build_drones_payload()

    # If not live and not debug, strip out any purely "debug" file-backed drones
    # but keep saved-config idle drones so Fleet Status always shows them.
    if not live_active and not debug_mode:
        # Only keep drones that came from saved configs (they have real details)
        drones = [d for d in drones if d.get("status") == "idle"]
    elif not live_active and debug_mode:
        drones = [{**d, "status": "debug"} for d in drones]

    return {
        "drones": drones,
        "count": len(drones),
        "video_dir": settings.MEDIA_VIDEOS_DIR,
        "live_active": live_active,
        "debug_mode": debug_mode,
    }


@router.get("/videos")
async def get_videos(include_debug: bool = False):
    """Get list of currently served local video files."""
    live_active = _is_live_stream_active()
    debug_mode = include_debug or settings.ALLOW_DEBUG_PLAYBACK
    if not live_active and not debug_mode:
        return {"videos": [], "count": 0, "video_dir": settings.MEDIA_VIDEOS_DIR, "live_active": False, "debug_mode": False}

    files = _list_video_files()
    videos = [
        {
            "name": p.name,
            "url": f"http://localhost:{settings.API_PORT}/videos/{p.name}",
            "size_bytes": p.stat().st_size,
        }
        for p in files
    ]
    return {
        "videos": videos,
        "count": len(videos),
        "video_dir": settings.MEDIA_VIDEOS_DIR,
        "live_active": live_active,
        "debug_mode": debug_mode,
    }


@router.get("/{drone_id}/feed")
async def get_drone_feed(drone_id: str):
    """Get live feed URL for a specific drone."""
    drones = _build_drones_payload()
    drone = next((d for d in drones if d["id"] == drone_id), None)
    if drone is None:
        return {"drone_id": drone_id, "feed_url": None, "status": "offline"}
    return {
        "drone_id": drone_id,
        "feed_url": drone["video_url"],
        "status": drone["status"],
        "stream_protocol": drone.get("stream_protocol", "file"),
    }
