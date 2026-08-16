from collections import defaultdict
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from app.config import settings
from app.db import get_db_cursor

router = APIRouter(prefix="/api/density", tags=["density"])

# Global state to hold density data from multiple concurrent CV pipelines
# Maps source URL to its latest density data
active_streams = {}
last_persisted_at_by_drone: dict[str, float] = {}
history_points_by_drone: dict[str, list[dict]] = defaultdict(list)
_db_warning_last_logged: dict[str, float] = {}  # Throttle DB unavailable warnings

ALLOWED_WINDOWS_SECONDS = {
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "6h": 6 * 60 * 60,
}

# Keep the old single-stream format for backwards compatibility
current_density_data = {
    "headcount": 0.0,
    "points_count": 0,
    "timestamp": None,
    "source": None,
    "drone_id": None,
    "drone_name": None,
    "zone": None,
    "latitude": None,
    "longitude": None,
    "altitude": None,
    "loop_video": True,
}

class DensityUpdate(BaseModel):
    headcount: float
    timestamp: float
    points_count: int
    source: str
    drone_id: Optional[str] = None
    drone_name: Optional[str] = None
    zone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    loop_video: Optional[bool] = True


def _prune_stale_streams() -> None:
    now = time.time()
    stale_sources = []
    for source, stream_data in active_streams.items():
        ts = stream_data.get("timestamp")
        if ts is None or (now - float(ts)) > settings.STREAM_STALE_SECONDS:
            stale_sources.append(source)

    for source in stale_sources:
        active_streams.pop(source, None)


def _safe_source_stem(source: str) -> str:
    parsed = urlparse(source)
    raw = Path(parsed.path if parsed.scheme else source).stem or "stream"
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw).strip("-")
    return normalized.lower() or "stream"


def _resolve_drone_identifier(drone_id: Optional[str], source: str) -> str:
    if drone_id and drone_id.strip():
        return drone_id.strip()
    return f"AUTO-{_safe_source_stem(source)}"


def _resolve_window_seconds(window: Optional[str], hours: Optional[int]) -> int:
    if window:
        key = window.lower().strip()
        if key not in ALLOWED_WINDOWS_SECONDS:
            raise HTTPException(status_code=400, detail="window must be one of: 15m, 30m, 1h, 2h, 6h")
        requested_seconds = ALLOWED_WINDOWS_SECONDS[key]
    elif hours is not None:
        clamped_hours = max(1, min(int(hours), int(settings.HISTORY_MAX_WINDOW_HOURS)))
        requested_seconds = clamped_hours * 3600
    else:
        default_hours = max(1, min(int(settings.HISTORY_DEFAULT_WINDOW_HOURS), int(settings.HISTORY_MAX_WINDOW_HOURS)))
        requested_seconds = default_hours * 3600

    max_seconds = int(settings.HISTORY_MAX_WINDOW_HOURS) * 3600
    return max(60, min(int(requested_seconds), max_seconds))


def _should_persist(drone_id: str, timestamp: float) -> bool:
    sample_seconds = max(1, int(settings.HISTORY_SAMPLE_SECONDS))
    previous = last_persisted_at_by_drone.get(drone_id)
    return previous is None or (timestamp - previous) >= sample_seconds


def _persist_density_point(data: "DensityUpdate", drone_id: str) -> None:
    latitude = float(data.latitude) if data.latitude is not None else 0.0
    longitude = float(data.longitude) if data.longitude is not None else 0.0
    altitude = float(data.altitude) if data.altitude is not None else 0.0
    name = data.drone_name or drone_id
    ts = float(data.timestamp)

    with get_db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO drones (
                id, name, latitude, longitude, altitude,
                battery_level, is_active, feed_url, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                altitude = excluded.altitude,
                is_active = excluded.is_active,
                feed_url = excluded.feed_url,
                updated_at = excluded.updated_at
            """,
            (
                drone_id, name, latitude, longitude, altitude,
                100.0, 1, data.source, ts,
            ),
        )
        cursor.execute(
            """
            INSERT INTO density_records (
                drone_id, latitude, longitude,
                person_count, density_level, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                drone_id, latitude, longitude,
                int(data.points_count), float(data.headcount), ts,
            ),
        )


def _append_memory_point(drone_id: str, timestamp: float, points_count: int, headcount: float) -> None:
    max_age_seconds = (int(settings.HISTORY_MAX_WINDOW_HOURS) * 3600) + 300
    cutoff = float(timestamp) - max_age_seconds

    series = history_points_by_drone[drone_id]
    series.append(
        {
            "timestamp": float(timestamp),
            "people_count": int(points_count),
            "density_level": float(headcount),
        }
    )

    while series and float(series[0]["timestamp"]) < cutoff:
        series.pop(0)


def _query_memory_history(drone_id: Optional[str], window_seconds: int, interval_seconds: int) -> dict:
    now = time.time()
    start_ts = now - window_seconds

    target_ids = [drone_id] if drone_id else list(history_points_by_drone.keys())
    series_response = []
    flat_history = []

    for target_id in target_ids:
        if not target_id:
            continue
        points = history_points_by_drone.get(target_id, [])
        buckets: dict[int, dict] = {}

        for point in points:
            point_ts = float(point["timestamp"])
            if point_ts < start_ts:
                continue
            bucket_ts = int(point_ts // interval_seconds) * interval_seconds
            bucket = buckets.setdefault(
                bucket_ts,
                {
                    "sum_people": 0.0,
                    "sum_density": 0.0,
                    "max_people": 0,
                    "samples": 0,
                },
            )
            people_value = float(point["people_count"])
            density_value = float(point["density_level"])
            bucket["sum_people"] += people_value
            bucket["sum_density"] += density_value
            bucket["max_people"] = max(bucket["max_people"], int(point["people_count"]))
            bucket["samples"] += 1

        drone_series = []
        for bucket_ts in sorted(buckets.keys()):
            aggregate = buckets[bucket_ts]
            samples = max(1, int(aggregate["samples"]))
            formatted = {
                "timestamp": datetime.utcfromtimestamp(bucket_ts).isoformat(),
                "people_count": float(aggregate["sum_people"]) / samples,
                "density_level": float(aggregate["sum_density"]) / samples,
                "max_people_count": int(aggregate["max_people"]),
                "samples": int(aggregate["samples"]),
            }
            drone_series.append(formatted)
            flat_history.append({"drone_id": target_id, **formatted})

        if drone_series:
            series_response.append({"drone_id": target_id, "points": drone_series})

    if drone_id:
        points = series_response[0]["points"] if series_response else []
        return {"points": points, "history": points}

    return {"series": series_response, "history": flat_history}

@router.post("/update")
async def update_current_density(data: DensityUpdate):
    """Receive live stream density data from the CV pipeline.
    
    Supports multiple concurrent streams. Each stream identified by source URL.
    """
    global current_density_data, active_streams
    _prune_stale_streams()
    resolved_drone_id = _resolve_drone_identifier(data.drone_id, data.source)
    
    # Store in multi-stream dictionary
    active_streams[data.source] = {
        "headcount": data.headcount,
        "points_count": data.points_count,
        "timestamp": data.timestamp,
        "source": data.source,
        "drone_id": resolved_drone_id,
        "drone_name": data.drone_name,
        "zone": data.zone,
        "latitude": data.latitude,
        "longitude": data.longitude,
        "altitude": data.altitude,
        "loop_video": data.loop_video,
    }
    
    # Also update the single-stream format for backwards compatibility
    current_density_data.update({
        "headcount": data.headcount,
        "points_count": data.points_count,
        "timestamp": data.timestamp,
        "source": data.source,
        "drone_id": resolved_drone_id,
        "drone_name": data.drone_name,
        "zone": data.zone,
        "latitude": data.latitude,
        "longitude": data.longitude,
        "altitude": data.altitude,
        "loop_video": data.loop_video,
    })

    _append_memory_point(
        drone_id=resolved_drone_id,
        timestamp=float(data.timestamp),
        points_count=int(data.points_count),
        headcount=float(data.headcount),
    )

    if _should_persist(resolved_drone_id, float(data.timestamp)):
        try:
            _persist_density_point(data, resolved_drone_id)
            last_persisted_at_by_drone[resolved_drone_id] = float(data.timestamp)
        except Exception as exc:
            # Keep the stream live even if DB write fails.
            # Only log once per 60 seconds per drone to avoid terminal spam.
            now_ts = time.time()
            last_warned = _db_warning_last_logged.get(resolved_drone_id, 0)
            if now_ts - last_warned > 60:
                print(f"[DB] Density persistence unavailable for {resolved_drone_id} ({exc}). Data is still live in memory.")
                _db_warning_last_logged[resolved_drone_id] = now_ts
    
    return {"status": "success"}

@router.get("/current")
async def get_current_density():
    """Get current crowd density data for all active zones."""
    _prune_stale_streams()
    return {
        "current_data": current_density_data,
        "active_streams": active_streams,
    }


@router.get("/history")
async def get_density_history(
    drone_id: Optional[str] = None,
    window: Optional[str] = Query(default=None, description="15m, 30m, 1h, 2h, or 6h"),
    hours: Optional[int] = Query(default=None, ge=1, le=24),
    interval_seconds: int = Query(default=15, ge=1, le=300),
    zone_id: Optional[str] = None,
):
    """Get historical density data from database.

    Backward compatible with old `hours` and `zone_id` params.
    """
    resolved_window_seconds = _resolve_window_seconds(window, hours)
    resolved_hours = resolved_window_seconds / 3600.0
    safe_interval = max(1, int(interval_seconds))

    try:
        with get_db_cursor() as (_, cursor):
            # timestamp column is a unix float
            cursor.execute(
                """
                SELECT
                    drone_id,
                    CAST(CAST(timestamp AS INTEGER) / ? AS INTEGER) * ? AS bucket_ts,
                    AVG(person_count) AS people_count,
                    AVG(density_level) AS density_level,
                    MAX(person_count) AS max_people_count,
                    COUNT(*) AS samples
                FROM density_records
                WHERE timestamp >= (? - ?)
                    AND (? IS NULL OR drone_id = ?)
                GROUP BY drone_id, bucket_ts
                ORDER BY bucket_ts ASC
                """,
                (
                    safe_interval, safe_interval,
                    time.time(), resolved_window_seconds,
                    drone_id, drone_id,
                ),
            )
            raw_rows = cursor.fetchall()
            # Convert epoch bucket_ts to ISO format
            rows = [
                {
                    **r,
                    "bucket_ts": datetime.utcfromtimestamp(float(r["bucket_ts"])) if r.get("bucket_ts") else None,
                }
                for r in raw_rows
            ]
    except Exception as exc:
        fallback = _query_memory_history(drone_id, resolved_window_seconds, safe_interval)
        return {
            "drone_id": drone_id,
            "window_hours": resolved_hours,
            "hours": resolved_hours,
            "interval_seconds": safe_interval,
            "zone_id": zone_id,
            "data_source": "memory",
            **fallback,
            "warning": f"database unavailable, using in-memory history: {exc}",
        }

    if drone_id:
        points = [
            {
                "timestamp": row["bucket_ts"].isoformat() if row["bucket_ts"] else None,
                "people_count": float(row["people_count"] or 0),
                "density_level": float(row["density_level"] or 0),
                "max_people_count": int(row["max_people_count"] or 0),
                "samples": int(row["samples"] or 0),
            }
            for row in rows
        ]
        return {
            "drone_id": drone_id,
            "window_hours": resolved_hours,
            "hours": resolved_hours,
            "interval_seconds": safe_interval,
            "points": points,
            "history": points,
            "zone_id": zone_id,
            "data_source": "database",
        }

    series_by_drone: dict[str, list[dict]] = {}
    flat_history: list[dict] = []
    for row in rows:
        key = row.get("drone_id") or "unknown"
        point = {
            "timestamp": row["bucket_ts"].isoformat() if row["bucket_ts"] else None,
            "people_count": float(row["people_count"] or 0),
            "density_level": float(row["density_level"] or 0),
            "max_people_count": int(row["max_people_count"] or 0),
            "samples": int(row["samples"] or 0),
        }
        series_by_drone.setdefault(key, []).append(point)
        flat_history.append({"drone_id": key, **point})

    return {
        "window_hours": resolved_hours,
        "hours": resolved_hours,
        "interval_seconds": safe_interval,
        "history": flat_history,
        "series": [
            {
                "drone_id": drone_key,
                "points": points,
            }
            for drone_key, points in series_by_drone.items()
        ],
        "zone_id": zone_id,
        "data_source": "database",
    }


@router.get("/heatmap")
async def get_heatmap_data():
    """Get heatmap data points for map visualization."""
    # TODO: Implement heatmap data generation
    return {"points": [], "timestamp": None}
