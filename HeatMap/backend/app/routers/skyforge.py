"""
SkyForge integration router for HeatMap.

Endpoints for accessing drone telemetry, missions, and camera feeds
from SkyForge GCS.
"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, Dict, List
from datetime import datetime
import logging

from app.models.skyforge import (
    TelemetryData, DroneStatus, Mission, CameraFeed, MissionWaypoint
)
from app.services.mavlink_telemetry import MAVLinkTelemetry

router = APIRouter(prefix="/api/skyforge", tags=["skyforge"])
logger = logging.getLogger("SkyForge")

# Global registry of connected drones
_drone_telemetry: Dict[str, MAVLinkTelemetry] = {}


@router.on_event("startup")
async def startup_skyforge():
    """Initialize SkyForge service."""
    logger.info("SkyForge integration ready")


@router.on_event("shutdown")
async def shutdown_skyforge():
    """Cleanup SkyForge connections."""
    for drone_id, telemetry in _drone_telemetry.items():
        try:
            telemetry.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting {drone_id}: {e}")


# ============================================================================
# Telemetry Endpoints
# ============================================================================

@router.post("/telemetry/connect")
async def connect_drone(
    drone_id: str = Query(..., description="Drone identifier"),
    connection_string: str = Query(default="udp:0.0.0.0:14550", 
                                   description="MAVLink connection string")
) -> Dict:
    """
    Connect to a drone via MAVLink.
    
    Examples:
        - UDP: `udp:0.0.0.0:14550` (primary GCS port)
        - UDP loopback: `udp:127.0.0.1:14550`
        - TCP: `tcp:127.0.0.1:5760`
        - Serial: `/dev/ttyUSB0` or `COM3`
    """
    try:
        if drone_id in _drone_telemetry:
            return {"status": "already_connected", "drone_id": drone_id}
        
        telemetry = MAVLinkTelemetry(drone_id, connection_string)
        if telemetry.connect():
            _drone_telemetry[drone_id] = telemetry
            return {
                "status": "connected",
                "drone_id": drone_id,
                "connection": connection_string
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to establish MAVLink connection")
    except Exception as e:
        logger.error(f"Connection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/telemetry/disconnect")
async def disconnect_drone(drone_id: str = Query(...)) -> Dict:
    """Disconnect from a drone."""
    if drone_id not in _drone_telemetry:
        raise HTTPException(status_code=404, detail="Drone not connected")
    
    try:
        _drone_telemetry[drone_id].disconnect()
        del _drone_telemetry[drone_id]
        return {"status": "disconnected", "drone_id": drone_id}
    except Exception as e:
        logger.error(f"Disconnect error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/telemetry/current")
async def get_current_telemetry(drone_id: str = Query(...)) -> TelemetryData:
    """
    Get real-time telemetry for a drone.
    
    Returns current GPS, attitude, speed, battery, and system status.
    """
    if drone_id not in _drone_telemetry:
        raise HTTPException(status_code=404, detail="Drone not connected")
    
    try:
        telemetry_handler = _drone_telemetry[drone_id]
        data = telemetry_handler.get_telemetry()
        
        return TelemetryData(
            drone_id=drone_id,
            timestamp=datetime.utcnow(),
            **data
        )
    except Exception as e:
        logger.error(f"Telemetry fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/telemetry/all")
async def get_all_telemetry() -> List[TelemetryData]:
    """Get telemetry for all connected drones."""
    results = []
    for drone_id, handler in _drone_telemetry.items():
        try:
            data = handler.get_telemetry()
            results.append(TelemetryData(
                drone_id=drone_id,
                timestamp=datetime.utcnow(),
                **data
            ))
        except Exception as e:
            logger.warning(f"Error fetching telemetry for {drone_id}: {e}")
    
    return results


@router.get("/status")
async def get_drone_status(drone_id: str = Query(...)) -> DroneStatus:
    """Get comprehensive drone status including telemetry."""
    if drone_id not in _drone_telemetry:
        raise HTTPException(status_code=404, detail="Drone not connected")
    
    handler = _drone_telemetry[drone_id]
    data = handler.get_telemetry()
    
    return DroneStatus(
        drone_id=drone_id,
        drone_name=f"Drone {drone_id}",  # TODO: Get from config
        source="mavlink",  # TODO: Get from config
        telemetry=TelemetryData(
            drone_id=drone_id,
            timestamp=datetime.utcnow(),
            **data
        ),
        is_connected=handler.is_connected,
        last_heartbeat=datetime.utcnow(),
        connection_type="mavlink"
    )


@router.get("/connected-drones")
async def list_connected_drones() -> Dict:
    """List all currently connected drones."""
    drones = {}
    for drone_id, handler in _drone_telemetry.items():
        drones[drone_id] = {
            "connected": handler.is_connected,
            "connection": handler.connection_string
        }
    
    return {
        "count": len(drones),
        "drones": drones
    }


# ============================================================================
# Flight Control Endpoints
# ============================================================================

@router.post("/control/arm")
async def arm_drone(drone_id: str = Query(...)) -> Dict:
    """Arm the drone (prepare for takeoff)."""
    if drone_id not in _drone_telemetry:
        raise HTTPException(status_code=404, detail="Drone not connected")
    
    success = _drone_telemetry[drone_id].arm()
    if success:
        return {"status": "armed", "drone_id": drone_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to arm drone")


@router.post("/control/disarm")
async def disarm_drone(drone_id: str = Query(...)) -> Dict:
    """Disarm the drone (stop motors)."""
    if drone_id not in _drone_telemetry:
        raise HTTPException(status_code=404, detail="Drone not connected")
    
    success = _drone_telemetry[drone_id].disarm()
    if success:
        return {"status": "disarmed", "drone_id": drone_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to disarm drone")


@router.post("/control/mode")
async def set_flight_mode(
    drone_id: str = Query(...),
    mode: str = Query(..., description="Flight mode (GUIDED, LAND, RTL, etc)")
) -> Dict:
    """Set drone flight mode."""
    if drone_id not in _drone_telemetry:
        raise HTTPException(status_code=404, detail="Drone not connected")
    
    success = _drone_telemetry[drone_id].set_mode(mode)
    if success:
        return {"status": "mode_set", "drone_id": drone_id, "mode": mode}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to set mode to {mode}")


# ============================================================================
# Mission Endpoints (Stubs for Future Implementation)
# ============================================================================

@router.post("/missions/create")
async def create_mission(
    drone_id: str = Query(...),
    waypoints: List[Dict] = Body(...)
) -> Dict:
    """Create a flight mission with waypoints."""
    # TODO: Implement mission creation
    raise HTTPException(status_code=501, detail="Mission creation not yet implemented")


@router.post("/missions/upload")
async def upload_mission(drone_id: str = Query(...), mission_id: str = Query(...)) -> Dict:
    """Upload mission to drone."""
    # TODO: Implement mission upload
    raise HTTPException(status_code=501, detail="Mission upload not yet implemented")

@router.post("/missions/start")
async def start_mission(drone_id: str = Query(...), mission_id: str = Query(...)) -> Dict:
    """Start executing a mission."""
    # TODO: Implement mission start
    raise HTTPException(status_code=501, detail="Mission start not yet implemented")


# ============================================================================
# Camera Feed Endpoints
# ============================================================================

@router.get("/camera-feed")
async def get_camera_feed(drone_id: str = Query(...)) -> CameraFeed:
    """Get camera feed URL and metadata for a drone."""
    if drone_id not in _drone_telemetry:
        raise HTTPException(status_code=404, detail="Drone not connected")
    
    # TODO: Get actual RTSP/HLS URL from drone config
    return CameraFeed(
        drone_id=drone_id,
        camera_name="Main Camera",
        rtsp_url="rtsp://192.168.1.100:554/stream",  # Placeholder
        feed_type="rtsp"
    )


# ============================================================================
# Health & Info Endpoints
# ============================================================================

@router.get("/health")
async def skyforge_health() -> Dict:
    """Health check for SkyForge integration."""
    return {
        "status": "healthy",
        "connected_drones": len(_drone_telemetry),
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/info")
async def get_skyforge_info() -> Dict:
    """Get SkyForge integration info."""
    return {
        "service": "SkyForge GCS",
        "version": "0.1.0",
        "capabilities": [
            "MAVLink telemetry",
            "Drone status monitoring",
            "Flight control (arm/disarm/mode)",
            "Camera feed management"
        ],
        "connected_drones": len(_drone_telemetry)
    }
