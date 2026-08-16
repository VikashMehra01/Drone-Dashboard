import numpy as np
from typing import Tuple

class CoordinateTransformer:
    def __init__(self, altitude: float, fov_h: float, fov_v: float, img_width: int, img_height: int, drone_lat: float, drone_lon: float):
        """
        Initialize the transformer with drone spatial metadata.
        
        Args:
            altitude: Drone altitude in meters.
            fov_h: Horizontal Field of View in degrees.
            fov_v: Vertical Field of View in degrees.
            img_width: Video frame width in pixels.
            img_height: Video frame height in pixels.
            drone_lat: Drone GPS latitude.
            drone_lon: Drone GPS longitude.
        """
        self.altitude = altitude
        self.fov_h = np.radians(fov_h)
        self.fov_v = np.radians(fov_v)
        self.img_width = img_width
        self.img_height = img_height
        
        self.drone_lat = drone_lat
        self.drone_lon = drone_lon
        
        # Calculate real-world footprint dimensions
        self.ground_width = 2 * float(self.altitude) * np.tan(self.fov_h / 2.0)
        self.ground_height = 2 * float(self.altitude) * np.tan(self.fov_v / 2.0)
        
        # Meters per pixel
        self.m_per_px_x = self.ground_width / float(self.img_width)
        self.m_per_px_y = self.ground_height / float(self.img_height)
        
        # Roughly 1 degree of latitude is ~111,320 meters
        self.meters_per_deg_lat = 111320.0
        # Longitude distance depends on latitude
        self.meters_per_deg_lon = 40075000.0 * np.cos(np.radians(self.drone_lat)) / 360.0

    def pixel_to_meters(self, px_x: int, px_y: int) -> Tuple[float, float]:
        """
        Convert pixel coordinates to meters offset from the center of the image (drone position).
        Assumes the camera is pointed straight down (nadir).
        Returns (offset_x, offset_y) in meters.
        """
        center_x = self.img_width / 2.0
        center_y = self.img_height / 2.0
        
        # Positive X is right, Positive Y is down (in image coords), 
        # so for map coords: positive Y is Forward (North, if drone faces North)
        offset_x = (px_x - center_x) * self.m_per_px_x
        offset_y = (center_y - px_y) * self.m_per_px_y # Invert Y so up is positive
        
        return offset_x, offset_y

    def pixel_to_gps(self, px_x: int, px_y: int, drone_heading: float = 0.0) -> Tuple[float, float]:
        """
        Convert pixel coordinates to GPS (latitude, longitude).
        Heading is the drone's yaw in degrees (0 = North).
        """
        offset_x, offset_y = self.pixel_to_meters(px_x, px_y)
        
        # Rotate offsets based on drone heading
        rad_heading = np.radians(drone_heading)
        rot_x = offset_x * np.cos(rad_heading) - offset_y * np.sin(rad_heading)
        rot_y = offset_x * np.sin(rad_heading) + offset_y * np.cos(rad_heading)
        
        # Calculate new GPS coordinates
        delta_lat = rot_y / self.meters_per_deg_lat
        delta_lon = rot_x / self.meters_per_deg_lon
        
        target_lat = self.drone_lat + delta_lat
        target_lon = self.drone_lon + delta_lon
        
        return target_lat, target_lon
