"""
Satellite Tile Provider - fetches ESRI World Imagery (real aerial/satellite)
tiles and composites them into a geo-referenced BGR canvas aligned with the
MultiBandMap2D metric coordinate system (East = +X, -North = +Y, origin =
first image GPS).

The coverage area **expands dynamically** as the drone's mapped footprint
grows: only newly-needed boundary tiles are fetched and the stitched canvas
is rebuilt incrementally.

**Offline-first design**: Gracefully degrades when the network is unavailable.
Cached tiles are always preferred.  Missing tiles display a placeholder
pattern instead of blank/black so the operator can see coverage gaps.
"""

import os
import math
import glob
import logging
import urllib.request
import numpy as np
import cv2
from pyproj import Proj

logger = logging.getLogger(__name__)

# --------------- Slippy-map helpers ---------------

def _lat_lon_to_tile(lat, lon, zoom):
    """Convert lat/lon (WGS-84) to slippy-map tile indices (x, y) at *zoom*."""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _tile_to_lat_lon(tx, ty, zoom):
    """Return the NW corner (lat, lon) of a tile."""
    n = 2 ** zoom
    lon = tx / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ty / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


# --------------- SatelliteTileProvider ---------------

# ESRI World Imagery - free, no API key, real aerial/satellite photos.
# Tile order is {z}/{y}/{x} (row before column).
_DEFAULT_TILE_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)


class SatelliteTileProvider:
    """
    Downloads satellite / aerial imagery tiles around a GPS centre, stitches
    them, and reprojects the result into the UTM metric frame used by the
    mapper.  The covered area **expands automatically** when the mapper's
    footprint exceeds the current tile range.

    Parameters
    ----------
    center_lat, center_lon : float
        WGS-84 coordinates of the map origin (typically the first image).
    area_meters : float
        *Initial* side length of the square area to cover (default 500 m).
        The area grows dynamically afterwards.
    zoom : int
        Tile zoom level (18 ≈ 0.6 m/px at equator - good for drone scale).
    tile_url : str
        URL template with ``{z}``, ``{x}``, ``{y}`` placeholders.
    cache_dir : str | None
        Disk tile cache path.  ``None`` → ``backend/.tile_cache/esri``.
    """

    TILE_PX = 256  # Standard Web-Mercator tile size

    def __init__(
        self,
        center_lat: float,
        center_lon: float,
        area_meters: float = 500.0,
        zoom: int = 18,
        tile_url: str = _DEFAULT_TILE_URL,
        cache_dir: str | None = None,
    ):
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.area_meters = area_meters
        self.zoom = zoom
        self.tile_url = tile_url

        # Disk cache - %APPDATA%/SkyForge/tiles/ (persists across installs)
        if cache_dir is None:
            appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
            cache_dir = os.path.join(appdata, "SkyForge", "tiles", "esri")
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

        # UTM projection (same logic as PoseExtractor)
        utm_zone = int((center_lon + 180) / 6) + 1
        self.proj = Proj(proj="utm", zone=utm_zone, ellps="WGS84")
        self.origin_east, self.origin_north = self.proj(center_lon, center_lat)

        # Per-tile image store  {(tx, ty): ndarray}  - survives expansion.
        self._tile_images: dict[tuple[int, int], np.ndarray] = {}

        # Offline resilience tracking
        self._offline_mode = False          # True after consecutive fetch failures
        self._consecutive_failures = 0
        self._total_fetched = 0
        self._total_cache_hits = 0
        self._total_fetch_failures = 0
        self._placeholder: np.ndarray | None = None   # lazy-created

        # Current tile index range (set by _compute_tile_range / ensure_coverage)
        self.tx_min = self.tx_max = self.ty_min = self.ty_max = 0

        # Determine initial tile range from area_meters
        self._compute_tile_range()

        # Stitched canvas & its metric bounds (rebuilt by _stitch)
        self._canvas: np.ndarray | None = None
        self._bounds_metric: tuple | None = None  # (east_min, east_max, north_min, north_max)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _compute_tile_range(self):
        """Set the initial tile range from *area_meters* around the centre."""
        half = self.area_meters / 2.0
        d_lat = half / 111_320.0
        d_lon = half / (111_320.0 * math.cos(math.radians(self.center_lat)))

        lat_min = self.center_lat - d_lat
        lat_max = self.center_lat + d_lat
        lon_min = self.center_lon - d_lon
        lon_max = self.center_lon + d_lon

        x_min, y_max = _lat_lon_to_tile(lat_min, lon_min, self.zoom)
        x_max, y_min = _lat_lon_to_tile(lat_max, lon_max, self.zoom)

        # 1-tile margin
        self.tx_min = max(x_min - 1, 0)
        self.tx_max = x_max + 1
        self.ty_min = max(y_min - 1, 0)
        self.ty_max = y_max + 1

    def _make_placeholder(self) -> np.ndarray:
        """Create a subtle checkerboard placeholder tile (256×256 BGR).
        Used when a tile cannot be fetched and is not in the cache."""
        if self._placeholder is not None:
            return self._placeholder
        tile = np.full((self.TILE_PX, self.TILE_PX, 3), 40, dtype=np.uint8)
        block = 32
        for r in range(0, self.TILE_PX, block):
            for c in range(0, self.TILE_PX, block):
                if (r // block + c // block) % 2 == 0:
                    tile[r:r + block, c:c + block] = 50
        # Small "OFFLINE" watermark in center
        cv2.putText(tile, "NO DATA", (55, 132),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.7, (70, 70, 70), 2, cv2.LINE_AA)
        self._placeholder = tile
        return self._placeholder

    def _fetch_tile(self, tx: int, ty: int) -> np.ndarray | None:
        """Return a 256×256 BGR tile - memory → disk cache → network → placeholder.

        Never returns ``None``.  If the tile cannot be fetched, a visible
        placeholder is returned so operators can see coverage gaps instead of
        black holes.
        """
        # 1) Already in memory?
        if (tx, ty) in self._tile_images:
            return self._tile_images[(tx, ty)]

        # 2) Disk cache?
        cache_path = os.path.join(self.cache_dir, f"{self.zoom}_{tx}_{ty}.png")
        if os.path.exists(cache_path):
            img = cv2.imread(cache_path, cv2.IMREAD_COLOR)
            if img is not None:
                self._tile_images[(tx, ty)] = img
                self._total_cache_hits += 1
                return img

        # 3) If we are in offline mode, skip the network entirely
        if self._offline_mode:
            placeholder = self._make_placeholder()
            self._tile_images[(tx, ty)] = placeholder
            return placeholder

        # 4) Network fetch
        url = self.tile_url.format(z=self.zoom, x=tx, y=ty)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SkyForge-GCS/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
            arr = np.frombuffer(data, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                cv2.imwrite(cache_path, img)
                self._tile_images[(tx, ty)] = img
                self._total_fetched += 1
                # Successful fetch resets failure counter
                self._consecutive_failures = 0
                if self._offline_mode:
                    self._offline_mode = False
                    logger.info("[Satellite] Network recovered - exiting offline mode")
                return img
        except Exception as e:
            self._consecutive_failures += 1
            self._total_fetch_failures += 1
            if self._consecutive_failures >= 3 and not self._offline_mode:
                self._offline_mode = True
                logger.warning(
                    "[Satellite] 3 consecutive fetch failures - entering OFFLINE mode. "
                    "Cached tiles will be used; missing tiles show placeholder."
                )
            else:
                logger.warning(f"[Satellite] Failed to fetch tile z={self.zoom} x={tx} y={ty}: {e}")

        # 5) Fallback: placeholder tile
        placeholder = self._make_placeholder()
        self._tile_images[(tx, ty)] = placeholder
        return placeholder

    def _fetch_range(self, tx_min, tx_max, ty_min, ty_max):
        """Download all tiles in the given range that aren't already cached."""
        new_count = 0
        for ty in range(ty_min, ty_max + 1):
            for tx in range(tx_min, tx_max + 1):
                if (tx, ty) not in self._tile_images:
                    self._fetch_tile(tx, ty)
                    new_count += 1
        return new_count

    def _stitch(self):
        """(Re-)stitch ``_canvas`` from ``_tile_images`` over the current range
        and recompute ``_bounds_metric``."""
        cols = self.tx_max - self.tx_min + 1
        rows = self.ty_max - self.ty_min + 1

        stitched = np.zeros((rows * self.TILE_PX, cols * self.TILE_PX, 3), dtype=np.uint8)

        for ty in range(self.ty_min, self.ty_max + 1):
            for tx in range(self.tx_min, self.tx_max + 1):
                tile_img = self._tile_images.get((tx, ty))
                if tile_img is None:
                    continue
                r = ty - self.ty_min
                c = tx - self.tx_min
                stitched[r * self.TILE_PX:(r + 1) * self.TILE_PX,
                         c * self.TILE_PX:(c + 1) * self.TILE_PX] = tile_img

        # Metric bounds (relative to mapper origin) --------------------------
        nw_lat, nw_lon = _tile_to_lat_lon(self.tx_min, self.ty_min, self.zoom)
        se_lat, se_lon = _tile_to_lat_lon(self.tx_max + 1, self.ty_max + 1, self.zoom)

        nw_east, nw_north = self.proj(nw_lon, nw_lat)
        se_east, se_north = self.proj(se_lon, se_lat)

        east_min = nw_east - self.origin_east
        east_max = se_east - self.origin_east
        north_min = se_north - self.origin_north
        north_max = nw_north - self.origin_north

        self._bounds_metric = (east_min, east_max, north_min, north_max)
        self._canvas = stitched

        logger.info(
            f"[Satellite] Stitched {cols}x{rows} tiles -> "
            f"{stitched.shape[1]}x{stitched.shape[0]} px, "
            f"metric E[{east_min:.0f}..{east_max:.0f}] N[{north_min:.0f}..{north_max:.0f}]"
        )

    # ------------------------------------------------------------------ #
    #  Dynamic expansion                                                   #
    # ------------------------------------------------------------------ #

    def _metric_to_latlon(self, east_m: float, north_m: float):
        """Convert mapper-relative metric coords back to WGS-84."""
        abs_east = east_m + self.origin_east
        abs_north = north_m + self.origin_north
        lon, lat = self.proj(abs_east, abs_north, inverse=True)
        return lat, lon

    def ensure_coverage(self, east_min: float, east_max: float,
                        north_min: float, north_max: float):
        """Expand tile range (and re-stitch) if the requested metric extent
        exceeds the current satellite coverage.

        A generous **buffer margin** of max(300 m, 75 % of span) is added on
        each side so we rarely need to re-expand during a flight.
        """
        east_span = east_max - east_min
        north_span = north_max - north_min
        buf_e = max(300.0, 0.75 * east_span)
        buf_n = max(300.0, 0.75 * north_span)

        req_east_min = east_min - buf_e
        req_east_max = east_max + buf_e
        req_north_min = north_min - buf_n
        req_north_max = north_max + buf_n

        # Convert buffered metric corners to lat/lon → tile indices
        # NW corner (min east, max north)
        nw_lat, nw_lon = self._metric_to_latlon(req_east_min, req_north_max)
        # SE corner (max east, min north)
        se_lat, se_lon = self._metric_to_latlon(req_east_max, req_north_min)

        new_tx_min, _ = _lat_lon_to_tile(nw_lat, nw_lon, self.zoom)
        _, new_ty_min = _lat_lon_to_tile(nw_lat, nw_lon, self.zoom)
        new_tx_max_raw, _ = _lat_lon_to_tile(se_lat, se_lon, self.zoom)
        _, new_ty_max_raw = _lat_lon_to_tile(se_lat, se_lon, self.zoom)

        # Tile y is inverted (smaller y = more north)
        need_tx_min = max(min(new_tx_min, new_tx_max_raw) - 1, 0)
        need_tx_max = max(new_tx_min, new_tx_max_raw) + 1
        need_ty_min = max(min(new_ty_min, new_ty_max_raw) - 1, 0)
        need_ty_max = max(new_ty_min, new_ty_max_raw) + 1

        # Check if expansion is needed
        if (need_tx_min >= self.tx_min and need_tx_max <= self.tx_max and
                need_ty_min >= self.ty_min and need_ty_max <= self.ty_max):
            return  # Already covered - fast-path

        # Expand range
        old = (self.tx_min, self.tx_max, self.ty_min, self.ty_max)
        self.tx_min = min(self.tx_min, need_tx_min)
        self.tx_max = max(self.tx_max, need_tx_max)
        self.ty_min = min(self.ty_min, need_ty_min)
        self.ty_max = max(self.ty_max, need_ty_max)

        new_tiles = self._fetch_range(self.tx_min, self.tx_max,
                                      self.ty_min, self.ty_max)
        self._stitch()
        logger.info(f"[Satellite] Expanded tile range {old} -> "
              f"({self.tx_min},{self.tx_max},{self.ty_min},{self.ty_max}), "
              f"fetched {new_tiles} new tiles")

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def build(self):
        """Download and stitch the initial tile set.  Call once after init.

        Gracefully handles offline scenarios - uses cached tiles where
        available and fills gaps with placeholder tiles.
        """
        n_tiles = (self.tx_max - self.tx_min + 1) * (self.ty_max - self.ty_min + 1)
        logger.info(f"[Satellite] Building initial tile set: {n_tiles} tiles at zoom {self.zoom}")
        self._fetch_range(self.tx_min, self.tx_max, self.ty_min, self.ty_max)
        if not self._tile_images:
            logger.warning("[Satellite] No tiles available (offline?) - satellite underlay disabled")
            return
        real_tiles = sum(1 for img in self._tile_images.values()
                         if img is not self._placeholder)
        if self._offline_mode:
            logger.warning(
                f"[Satellite] OFFLINE MODE - {real_tiles}/{n_tiles} tiles from cache, "
                f"rest are placeholders"
            )
        else:
            logger.info(f"[Satellite] {real_tiles} tiles loaded successfully")
        self._stitch()

    def get_cache_stats(self) -> dict:
        """Return statistics about the tile cache for UI display.

        Returns
        -------
        dict with keys:
            cached_files   – number of .png files on disk
            cache_size_mb  – total size of cache directory (MB)
            memory_tiles   – tiles currently held in memory
            fetched        – tiles downloaded this session
            cache_hits     – tiles served from disk cache this session
            fetch_failures – failed network fetches this session
            offline_mode   – whether the provider is in offline mode
            zoom           – current zoom level
        """
        # Count cached files on disk
        cached_files = 0
        cache_bytes = 0
        try:
            pattern = os.path.join(self.cache_dir, "*.png")
            files = glob.glob(pattern)
            cached_files = len(files)
            cache_bytes = sum(os.path.getsize(f) for f in files)
        except OSError:
            pass

        return {
            "cached_files": cached_files,
            "cache_size_mb": round(cache_bytes / (1024 * 1024), 1),
            "memory_tiles": len(self._tile_images),
            "fetched": self._total_fetched,
            "cache_hits": self._total_cache_hits,
            "fetch_failures": self._total_fetch_failures,
            "offline_mode": self._offline_mode,
            "zoom": self.zoom,
        }

    def get_background_for_render(self, tile_keys, tile_size, resolution,
                                  quality_lvl=0):
        """
        Return a BGR canvas sized to match the mapper's tile grid, with
        satellite imagery warped into the correct position.

        Automatically expands tile coverage if the mapper's extent has grown
        beyond the currently downloaded area.

        Parameters
        ----------
        tile_keys : list of (tx, ty)
            Current mapper tile keys.
        tile_size : int
            Mapper tile size in pixels.
        resolution : float
            Mapper resolution in metres/pixel.
        quality_lvl : int
            Quality level (0 = full).

        Returns
        -------
        canvas : ndarray (H, W, 3) uint8  or  None
        """
        if not tile_keys:
            return None

        # ---- Mapper grid metric extent ----
        minx = min(k[0] for k in tile_keys)
        maxx = max(k[0] for k in tile_keys)
        miny = min(k[1] for k in tile_keys)
        maxy = max(k[1] for k in tile_keys)

        canvas_east_min = minx * tile_size * resolution
        canvas_east_max = (maxx + 1) * tile_size * resolution
        canvas_north_max = -(miny * tile_size * resolution)
        canvas_north_min = -((maxy + 1) * tile_size * resolution)

        # ---- Dynamic expansion ----
        self.ensure_coverage(canvas_east_min, canvas_east_max,
                             canvas_north_min, canvas_north_max)

        if self._canvas is None or self._bounds_metric is None:
            return None

        east_min_sat, east_max_sat, north_min_sat, north_max_sat = self._bounds_metric

        ts = tile_size // (2 ** quality_lvl)
        canvas_w = (maxx - minx + 1) * ts
        canvas_h = (maxy - miny + 1) * ts

        sat_h, sat_w = self._canvas.shape[:2]

        res_q = resolution * (2 ** quality_lvl)

        east_span = east_max_sat - east_min_sat
        north_span = north_max_sat - north_min_sat
        if east_span == 0 or north_span == 0:
            return None

        A = res_q / east_span * sat_w
        B = (canvas_east_min - east_min_sat) / east_span * sat_w
        C = res_q / north_span * sat_h
        D = (north_max_sat - canvas_north_max) / north_span * sat_h

        M = np.array([[A, 0, B],
                       [0, C, D]], dtype=np.float64)

        canvas = cv2.warpAffine(
            self._canvas, M, (canvas_w, canvas_h),
            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0),
        )

        return canvas
