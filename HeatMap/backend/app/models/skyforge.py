"""
SkyForge telemetry data models.

Represents drone telemetry data from MAVLink-connected drones,
used by both SkyForge GCS and HeatMap dashboard.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class TelemetryData(BaseModel):
    """Real-time drone telemetry from MAVLink."""
    drone_id: str = Field(..., description="Unique drone identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # GPS & Position
    latitude: float = Field(default=0.0, description="Latitude in decimal degrees")
    longitude: float = Field(default=0.0, description="Longitude in decimal degrees")
    altitude_msl: float = Field(default=0.0, description="Altitude above sea level (meters)")
    altitude_agl: float = Field(default=0.0, description="Altitude above ground level (meters)")
    
    # Attitude
    roll: float = Field(default=0.0, description="Roll angle in degrees")
    pitch: float = Field(default=0.0, description="Pitch angle in degrees")
    yaw: float = Field(default=0.0, description="Yaw angle in degrees")
    
    # Speed
    airspeed: float = Field(default=0.0, description="Airspeed in m/s")
    groundspeed: float = Field(default=0.0, description="Groundspeed in m/s")
    
    # Power
    battery_level: float = Field(default=100.0, description="Battery level 0-100%")
    battery_voltage: float = Field(default=0.0, description="Battery voltage in volts")
    battery_current: float = Field(default=0.0, description="Battery current in amps")
    
    # System status
    is_armed: bool = Field(default=False, description="Whether drone is armed")
    is_flying: bool = Field(default=False, description="Whether drone is in flight")
    mode: str = Field(default="UNKNOWN", description="Flight mode (STABILIZE, ALT_HOLD, etc)")
    
    # Gimbal (optional)
    gimbal_pitch: Optional[float] = Field(default=None, description="Gimbal pitch angle")
    gimbal_roll: Optional[float] = Field(default=None, description="Gimbal roll angle")
    gimbal_yaw: Optional[float] = Field(default=None, description="Gimbal yaw angle")


class DroneStatus(BaseModel):
    """Extended drone status combining config + telemetry."""
    drone_id: str
    drone_name: str
    source: str  # RTSP URL or device
    
    # Latest telemetry
    telemetry: Optional[TelemetryData] = None
    
    # Connection status
    is_connected: bool = False
    last_heartbeat: Optional[datetime] = None
    connection_type: str = Field(default="mavlink", description="mavlink, simulated, etc")


class MissionWaypoint(BaseModel):
    """A waypoint in a flight mission."""
    sequence: int
    latitude: float
    longitude: float
    altitude: float
    hold_time: int = Field(default=0, description="Hold time at waypoint in seconds")
    acceptance_radius: float = Field(default=5.0, description="Acceptance radius in meters")


class Mission(BaseModel):
    """Flight mission for a drone."""
    mission_id: str
    drone_id: str
    waypoints: list[MissionWaypoint]
    is_active: bool = False
    current_waypoint: int = 0


class CameraFeed(BaseModel):
    """Camera feed metadata."""
    drone_id: str
    camera_name: str = Field(default="Main Camera")
    rtsp_url: Optional[str] = None
    hls_url: Optional[str] = None
    feed_type: str = Field(default="rtsp", description="rtsp, http, mjpeg, etc")
    resolution: str = Field(default="1920x1080")
    fps: int = Field(default=30)
