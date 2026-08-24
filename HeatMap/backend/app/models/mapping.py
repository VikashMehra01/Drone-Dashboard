"""
SkyForge orthomosaic mapping data models.

Represents the state of the multi-band stitching pipeline, used by
both SkyForge GCS and the HeatMap dashboard.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Tuple


class FeedImageResult(BaseModel):
    """Result of feeding one image into the mapper."""
    status: str
    message: str


class ResetMapRequest(BaseModel):
    """Optional overrides applied when resetting the map."""
    resolution: Optional[float] = Field(default=None, description="Metres per pixel")
    band_num: Optional[int] = Field(default=None, description="Laplacian pyramid levels")
    tile_size: Optional[int] = Field(default=None, description="Tile size in pixels")


class MapperStatus(BaseModel):
    """Aggregate performance + tile stats for the current mapping session."""
    n_frames: int = 0
    tile_count: int = 0
    tile_memory_mb: float = 0.0
    area_m2: float = 0.0
    fps: float = 0.0
    avg_total_ms: float = 0.0
    last_total_ms: float = 0.0


class CoverageData(BaseModel):
    """Flight path + image footprints, for a coverage/QA overlay."""
    flight_path: List[Tuple[float, float]] = Field(default_factory=list)
    footprints: List[List[Tuple[float, float]]] = Field(default_factory=list)
    bounds: Optional[Tuple[float, float, float, float]] = None
    area_m2: float = 0.0
    frame_count: int = 0
