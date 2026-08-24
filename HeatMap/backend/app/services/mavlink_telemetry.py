"""
MAVLink telemetry service for SkyForge integration.

Provides real-time drone telemetry via MAVLink protocol.
Extracted and adapted from SkyForge's mavlink_feed.py.
"""

import os
import logging
import threading
from typing import Optional, Dict
from collections import deque
from datetime import datetime, timezone
from threading import Thread, Lock

logger = logging.getLogger("SkyForge.Telemetry")

# Set MAVLink protocol version
os.environ.setdefault("MAVLINK20", "1")

try:
    from pymavlink.dialects.v20 import ardupilotmega as mavlink
    from pymavlink import mavutil
except ImportError:
    logger.warning("pymavlink not installed - MAVLink telemetry disabled")
    mavlink = None
    mavutil = None

try:
    from scipy.spatial.transform import Rotation as Rot
except ImportError:
    Rot = None
    logger.debug("scipy not available - gimbal quaternion parsing disabled")


class MAVLinkTelemetry:
    """
    Real-time MAVLink telemetry handler.
    
    Maintains connection to drone flight controller and parses:
    - Heartbeat (armed, mode, system status)
    - GPS (position, altitude)
    - Attitude (roll, pitch, yaw)
    - Speed (airspeed, groundspeed)
    - Battery (voltage, current, percentage)
    - Gimbal (optional, if available)
    """
    
    def __init__(self, drone_id: str, connection_string: str = "udp:0.0.0.0:14550"):
        """
        Initialize MAVLink telemetry handler.
        
        Args:
            drone_id: Unique drone identifier
            connection_string: MAVLink connection string (e.g., "udp:0.0.0.0:14550")
        """
        if not mavlink or not mavutil:
            raise RuntimeError("pymavlink not installed")
        
        self.drone_id = drone_id
        self.connection_string = connection_string
        self.mav = None
        self.is_connected = False
        self._lock = Lock()
        self._stop_event = threading.Event()
        
        # Latest telemetry state
        self.latest_telemetry = {
            "latitude": 0.0,
            "longitude": 0.0,
            "altitude_msl": 0.0,
            "altitude_agl": 0.0,
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": 0.0,
            "airspeed": 0.0,
            "groundspeed": 0.0,
            "battery_level": 100.0,
            "battery_voltage": 0.0,
            "battery_current": 0.0,
            "is_armed": False,
            "is_flying": False,
            "mode": "UNKNOWN",
            "gimbal_pitch": None,
            "gimbal_roll": None,
            "gimbal_yaw": None,
        }
        
        self.message_queue = deque(maxlen=1000)
    
    def connect(self) -> bool:
        """
        Establish MAVLink connection to drone.
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            if not mavutil:
                raise RuntimeError("pymavlink not installed")
            
            logger.info(f"Connecting to MAVLink on {self.connection_string}...")
            self.mav = mavutil.mavlink_connection(self.connection_string)
            self.is_connected = True
            logger.info(f"Connected to {self.drone_id} via {self.connection_string}")
            
            # Start telemetry reading thread
            self._reader_thread = Thread(target=self._read_telemetry_loop, daemon=True)
            self._reader_thread.start()
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to MAVLink: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """Disconnect from drone."""
        self._stop_event.set()
        if self.mav:
            self.mav.close()
        self.is_connected = False
        logger.info(f"Disconnected from {self.drone_id}")
    
    def _read_telemetry_loop(self):
        """Read MAVLink messages in background thread."""
        while not self._stop_event.is_set():
            try:
                msg = self.mav.recv_match(timeout=1)
                if msg:
                    self.message_queue.append(msg)
                    self._process_message(msg)
            except Exception as e:
                logger.error(f"Error reading MAVLink message: {e}")
                self.is_connected = False
                break
    
    def _process_message(self, msg):
        """Process individual MAVLink message."""
        if msg.get_type() == "HEARTBEAT":
            self._handle_heartbeat(msg)
        elif msg.get_type() == "GPS_RAW_INT":
            self._handle_gps(msg)
        elif msg.get_type() == "ATTITUDE":
            self._handle_attitude(msg)
        elif msg.get_type() == "VFR_HUD":
            self._handle_vfr_hud(msg)
        elif msg.get_type() == "BATTERY_STATUS":
            self._handle_battery(msg)
        elif msg.get_type() == "GIMBAL_DEVICE_ATTITUDE_STATUS":
            self._handle_gimbal(msg)
    
    def _handle_heartbeat(self, msg):
        """Parse HEARTBEAT message (armed state, mode, system status)."""
        with self._lock:
            self.latest_telemetry["is_armed"] = msg.base_mode & mavlink.MAV_MODE_FLAG_ARMED_ARMED
            self.latest_telemetry["is_flying"] = (msg.base_mode & mavlink.MAV_MODE_FLAG_AUTO_ENABLED) or \
                                                  (msg.base_mode & mavlink.MAV_MODE_FLAG_GUIDED_ENABLED)
            # Mode lookup (simplified)
            mode_map = {
                0: "STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "AUTO",
                4: "GUIDED", 5: "LOITER", 6: "RTL", 7: "CIRCLE",
                8: "POSHOLD", 9: "BRAKE", 10: "THROW", 11: "AVOID_ADSB"
            }
            self.latest_telemetry["mode"] = mode_map.get(msg.custom_mode, "UNKNOWN")
    
    def _handle_gps(self, msg):
        """Parse GPS_RAW_INT message (position and altitude)."""
        with self._lock:
            self.latest_telemetry["latitude"] = msg.lat / 1e7  # Convert from raw format
            self.latest_telemetry["longitude"] = msg.lon / 1e7
            self.latest_telemetry["altitude_msl"] = msg.alt / 1000.0  # mm to m
    
    def _handle_attitude(self, msg):
        """Parse ATTITUDE message (roll, pitch, yaw in radians)."""
        import math
        with self._lock:
            self.latest_telemetry["roll"] = math.degrees(msg.roll)
            self.latest_telemetry["pitch"] = math.degrees(msg.pitch)
            self.latest_telemetry["yaw"] = math.degrees(msg.yaw)
    
    def _handle_vfr_hud(self, msg):
        """Parse VFR_HUD message (speed and altitude)."""
        with self._lock:
            self.latest_telemetry["airspeed"] = msg.airspeed
            self.latest_telemetry["groundspeed"] = msg.groundspeed
            self.latest_telemetry["altitude_agl"] = msg.alt  # AGL in meters
    
    def _handle_battery(self, msg):
        """Parse BATTERY_STATUS message (battery info)."""
        with self._lock:
            # Battery remaining as percentage (0-100)
            if hasattr(msg, "battery_remaining"):
                self.latest_telemetry["battery_level"] = msg.battery_remaining
            # Voltage in millivolts
            if hasattr(msg, "voltages") and msg.voltages:
                self.latest_telemetry["battery_voltage"] = msg.voltages[0] / 1000.0
            # Current in centi-amps
            if hasattr(msg, "current_battery"):
                self.latest_telemetry["battery_current"] = msg.current_battery / 100.0
    
    def _handle_gimbal(self, msg):
        """Parse GIMBAL_DEVICE_ATTITUDE_STATUS message (gimbal orientation)."""
        if not Rot:
            return
        try:
            # Extract quaternion from gimbal message
            q = [msg.q[0], msg.q[1], msg.q[2], msg.q[3]]
            rot = Rot.from_quat(q)
            angles = rot.as_euler('xyz', degrees=True)
            
            with self._lock:
                self.latest_telemetry["gimbal_roll"] = angles[0]
                self.latest_telemetry["gimbal_pitch"] = angles[1]
                self.latest_telemetry["gimbal_yaw"] = angles[2]
        except Exception as e:
            logger.debug(f"Gimbal parsing error: {e}")
    
    def get_telemetry(self) -> Dict:
        """Get latest telemetry data."""
        with self._lock:
            return self.latest_telemetry.copy()
    
    def set_mode(self, mode_name: str) -> bool:
        """Set drone flight mode (e.g., 'GUIDED', 'LAND')."""
        if not self.is_connected:
            logger.error("Cannot set mode - not connected")
            return False
        
        mode_map = {
            "STABILIZE": 0, "ACRO": 1, "ALT_HOLD": 2, "AUTO": 3,
            "GUIDED": 4, "LOITER": 5, "RTL": 6, "CIRCLE": 7,
            "POSHOLD": 8, "BRAKE": 9, "LAND": 9
        }
        
        mode_id = mode_map.get(mode_name.upper())
        if mode_id is None:
            logger.error(f"Unknown mode: {mode_name}")
            return False
        
        try:
            self.mav.set_mode(mode_id)
            logger.info(f"Set {self.drone_id} to {mode_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to set mode: {e}")
            return False
    
    def arm(self) -> bool:
        """Arm the drone."""
        if not self.is_connected:
            return False
        try:
            self.mav.arducopter_arm()
            logger.info(f"Armed {self.drone_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to arm: {e}")
            return False
    
    def disarm(self) -> bool:
        """Disarm the drone."""
        if not self.is_connected:
            return False
        try:
            self.mav.arducopter_disarm()
            logger.info(f"Disarmed {self.drone_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to disarm: {e}")
            return False
