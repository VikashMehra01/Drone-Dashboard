"""
Density Calculator Service
Computes crowd density from person detections and generates heatmap data.
"""


class DensityCalculator:
    def __init__(self, grid_size: int = 50):
        self.grid_size = grid_size

    def compute_density(self, detections: list, frame_width: int, frame_height: int):
        """Compute density grid from a list of person detections."""
        # TODO: Divide frame into grid cells
        # TODO: Count persons per cell
        # TODO: Normalize density values (0.0 - 1.0)
        return []

    def generate_heatmap_data(self, density_grid: list, geo_bounds: dict):
        """Convert density grid to geo-referenced heatmap data points."""
        # TODO: Map grid cells to lat/lng coordinates
        # TODO: Return list of {lat, lng, intensity} points
        return []

    def get_density_level(self, person_count: int, area: float) -> str:
        """Classify density level based on person count per area."""
        # TODO: Implement classification (low, medium, high, critical)
        return "low"
