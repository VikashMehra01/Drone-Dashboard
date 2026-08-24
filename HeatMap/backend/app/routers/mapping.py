"""
SkyForge orthomosaic mapping router for HeatMap.

Wraps SkyForge's MapperService (ported into app/services/mapping/) as
headless REST endpoints, so the web dashboard can drive the same
multi-band stitching pipeline used by the desktop app, without PyQt.
"""

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import Response
from typing import Dict

from app.models.mapping import (
    FeedImageResult, ResetMapRequest, MapperStatus, CoverageData,
)
from app.services.mapping.mapper_service import MapperService

router = APIRouter(prefix="/api/mapping", tags=["mapping"])

service = MapperService.get_instance()


@router.post("/feed-image", response_model=FeedImageResult)
async def feed_image(file: UploadFile = File(...)):
    """Feed one image (with DJI XMP GPS/gimbal metadata) into the mapper."""
    contents = await file.read()
    result = service.process_image(contents)
    return FeedImageResult(**result)


@router.get("/latest")
async def get_latest_map(which: str = "main"):
    """Get the current stitched map as a JPEG image.

    `which`: 'main', 'raw', or 'optimized' (raw/optimized only populated
    when comparison_mode has been enabled on the service).
    """
    img_bytes = service.get_map_image(which=which)
    if img_bytes is None:
        return Response(content=b"", media_type="image/jpeg", status_code=204)
    return Response(content=img_bytes, media_type="image/jpeg")


@router.post("/reset")
async def reset_map(params: ResetMapRequest = ResetMapRequest()) -> Dict:
    service.reset_map(
        resolution=params.resolution,
        band_num=params.band_num,
        tile_size=params.tile_size,
    )
    return {"status": "reset"}


@router.get("/status", response_model=MapperStatus)
async def get_status():
    """Aggregate performance + tile stats for the current mapping session."""
    perf = service.get_performance_summary()
    if perf is None:
        return MapperStatus()
    return MapperStatus(
        n_frames=perf["n_frames"],
        tile_count=perf["tile_count"],
        tile_memory_mb=perf["tile_memory_mb"],
        area_m2=service.mapper.get_coverage_data().get("area_m2", 0.0),
        fps=perf["fps"],
        avg_total_ms=perf["avg_total_ms"],
        last_total_ms=perf["last_total_ms"],
    )


@router.get("/coverage", response_model=CoverageData)
async def get_coverage():
    """Flight path + per-frame footprints + coverage area, for a QA overlay."""
    data = service.mapper.get_coverage_data()
    bounds = data["bounds"]
    return CoverageData(
        flight_path=[tuple(map(float, p)) for p in data["flight_path"]],
        footprints=[[tuple(map(float, pt)) for pt in fp] for fp in data["footprints"]],
        bounds=tuple(float(b) for b in bounds) if bounds is not None else None,
        area_m2=data["area_m2"],
        frame_count=len(data["footprints"]),
    )


@router.get("/health")
async def mapping_health() -> Dict:
    return {"status": "healthy", "frames_processed": len(service.metrics_log)}


@router.get("/info")
async def get_mapping_info() -> Dict:
    return {
        "service": "SkyForge Orthomosaic Mapper",
        "version": "0.1.0",
        "capabilities": [
            "DJI XMP pose extraction",
            "Multi-band blended stitching",
            "Optional pose-graph optimization",
            "Optional satellite underlay",
        ],
        "frames_processed": len(service.metrics_log),
    }
