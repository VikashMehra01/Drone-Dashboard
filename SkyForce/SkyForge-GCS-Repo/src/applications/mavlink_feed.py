"""
MAVLink Telemetry Bridge - Real-time telemetry and camera feed integration.

Provides:
  - MAVLinkTelemetry: parses MAVLink heartbeat, GPS, and attitude
  - CameraCapture: opens webcam or RTSP streams
  - frame_to_tagged_jpeg: embeds telemetry as EXIF metadata on frames
"""

import time
import logging
import cv2
import numpy as np
import os
import struct
from threading import Thread, Lock, current_thread
from collections import deque
from datetime import datetime, timezone
from math import isfinite

logger = logging.getLogger(__name__)
os.environ.setdefault("MAVLINK20", "1")

try:
    from gstreamer_capture import GStreamerCapture
except Exception:  # pragma: no cover - optional backend
    GStreamerCapture = None

# Try to import pymavlink; fall back gracefully if not available
try:
    from pymavlink.dialects.v20 import ardupilotmega as mavlink
except ImportError:
    logger.warning("pymavlink not installed - MAVLink will not work. Install via: pip install pymavlink")
    mavlink = None

# Try to import scipy for quaternion conversion (gimbal parsing)
try:
    from scipy.spatial.transform import Rotation as Rot
except ImportError:
    Rot = None
    logger.debug("scipy not available; gimbal quaternion parsing will be disabled")

# MAVLink connection endpoints (tried in order during auto-discovery)
# SAFETY NOTE: Binding to the SAME port that your real GCS uses (e.g.
# QGroundControl on 14550) will STEAL telemetry packets from the pilot.
# Prefer a dedicated forwarded port (14551, 14445) or TCP to avoid
# starving the primary GCS of data.
MAVLINK_ENDPOINTS = [
    "udp:0.0.0.0:14550",       # Primary GCS port - LAST resort (may conflict with QGC/MK15)
    "udp:127.0.0.1:14550",
    "udp:0.0.0.0:14551",       # Secondary MAVLink output (safe - won't steal from QGC)
    "udp:0.0.0.0:14445",       # QGC forwarded output
    "tcp:127.0.0.1:14445",     # ADB-forwarded TCP from MK15
    "tcp:127.0.0.1:5760",      # SITL / alternative
    "udp:127.0.0.1:14445",
]

DEFAULT_HDOP_LIMIT = 5.0      # HDOP threshold for GPS quality
DEFAULT_MIN_ALTITUDE = 2.0    # Minimum altitude (m AGL) for frame processing


class MAVLinkTelemetry:
    """Connect to a MAVLink endpoint and extract GPS, attitude, gimbal, and health data."""

    def __init__(self, hdop_limit: float = DEFAULT_HDOP_LIMIT):
        self.mav_connection = None
        self.mav_thread = None
        self._running = False
        self._lock = Lock()
        self._snapshot = {
            # Aircraft body angles (from ATTITUDE)
            "lat": 0, "lon": 0, "alt_rel": 0, "alt_abs": 0,
            "vx": 0, "vy": 0, "vz": 0,
            "yaw": 0, "roll": 0, "pitch": 0,
            # Gimbal angles (from MOUNT_ORIENTATION / GIMBAL_DEVICE_ATTITUDE_STATUS)
            "gimbal_roll": None,
            "gimbal_pitch": None,
            "gimbal_yaw": None,
            "has_gimbal": False,
            "gimbal_source": None,
            # GPS quality
            "satellites": 0, "gps_fix": 0, "hdop": 999,
            "timestamp": 0, "msg_count": 0, "last_msg_type": None,
            "msg_types_seen": {},
        }
        self.hdop_limit = hdop_limit
        self._last_gps_time = 0
        self._last_update_time = 0
        self._stale_threshold_s = 5.0
        self._raw_records = deque()

    @staticmethod
    def _jsonable_value(value):
        """Convert pymavlink field values into JSON-safe values."""
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, bytearray):
            return bytes(value).hex()
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, (list, tuple)):
            return [MAVLinkTelemetry._jsonable_value(v) for v in value]
        if isinstance(value, dict):
            return {
                str(k): MAVLinkTelemetry._jsonable_value(v)
                for k, v in value.items()
            }
        return value

    def _message_to_raw_record(self, msg, mtype: str) -> dict:
        """Record the full MAVLink payload so unknown fields can be inspected later."""
        try:
            fields = msg.to_dict()
            fields.pop("mavpackettype", None)
        except Exception:
            fields = {
                name: getattr(msg, name, None)
                for name in getattr(msg, "fieldnames", [])
            }

        raw_bytes_hex = None
        try:
            raw_bytes = msg.get_msgbuf()
            if raw_bytes:
                raw_bytes_hex = bytes(raw_bytes).hex()
        except Exception:
            pass

        return {
            "received_unix": time.time(),
            "type": mtype,
            "src_system": msg.get_srcSystem() if hasattr(msg, "get_srcSystem") else None,
            "src_component": msg.get_srcComponent() if hasattr(msg, "get_srcComponent") else None,
            "msg_id": msg.get_msgId() if hasattr(msg, "get_msgId") else None,
            "fields": self._jsonable_value(fields),
            "raw_hex": raw_bytes_hex,
        }

    def _set_gimbal_degrees(
        self,
        roll: float | None,
        pitch: float | None,
        yaw: float | None,
        source: str,
    ):
        """Store gimbal attitude in degrees when at least one angle is valid."""
        vals = (roll, pitch, yaw)
        if not any(v is not None and isfinite(float(v)) for v in vals):
            return
        if roll is not None and isfinite(float(roll)):
            self._snapshot["gimbal_roll"] = float(roll)
        if pitch is not None and isfinite(float(pitch)):
            self._snapshot["gimbal_pitch"] = float(pitch)
        if yaw is not None and isfinite(float(yaw)):
            self._snapshot["gimbal_yaw"] = float(yaw)
        self._snapshot["has_gimbal"] = True
        self._snapshot["gimbal_source"] = source
        self._snapshot["timestamp"] = time.time()

    def _set_gimbal_from_quaternion(self, q, source: str):
        """Convert MAVLink quaternion [w, x, y, z] to yaw, pitch, roll degrees."""
        if Rot is None or q is None or len(q) < 4:
            return
        rot = Rot.from_quat([q[1], q[2], q[3], q[0]])  # scipy uses [x, y, z, w]
        euler = rot.as_euler('ZYX', degrees=True)
        self._set_gimbal_degrees(
            roll=euler[2],
            pitch=euler[1],
            yaw=euler[0],
            source=source,
        )

    def connect(self, connection_str: str | None = None) -> bool:
        """Connect to MAVLink endpoint. Auto-detects if connection_str is None.
        
        Returns True on successful heartbeat reception.
        """
        if mavlink is None:
            logger.error("pymavlink not available")
            return False

        try:
            from pymavlink import mavutil
        except ImportError:
            logger.error("pymavutil not available")
            return False

        endpoints = [connection_str] if connection_str else MAVLINK_ENDPOINTS
        for ep in endpoints:
            try:
                logger.info(f"Trying MAVLink endpoint: {ep}")
                conn = mavutil.mavlink_connection(ep, baud=57600, source_system=255)
                logger.info("Waiting for heartbeat ...")
                hb = conn.wait_heartbeat(timeout=5)
                if hb:
                    logger.info(
                        "Heartbeat OK - system %d, component %d, autopilot %d, type %d",
                        conn.target_system, conn.target_component,
                        hb.autopilot, hb.type,
                    )
                    self.mav_connection = conn
                    mtype = hb.get_type()
                    with self._lock:
                        self._snapshot["msg_count"] += 1
                        self._snapshot["last_msg_type"] = mtype
                        msg_types = self._snapshot.setdefault("msg_types_seen", {})
                        msg_types[mtype] = msg_types.get(mtype, 0) + 1
                        self._raw_records.append(self._message_to_raw_record(hb, mtype))
                    return True
                else:
                    logger.warning(f"No heartbeat on {ep}")
                    try:
                        conn.close()
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug(f"Failed on {ep}: {exc}")
        logger.error("Could not connect to any MAVLink endpoint")
        return False

    def start(self) -> bool:
        """Start receiving telemetry in background thread."""
        if not self.mav_connection:
            logger.error("Not connected to MAVLink")
            return False
        self._running = True
        self.mav_thread = Thread(target=self._receive_loop, daemon=True)
        self.mav_thread.start()
        logger.info("MAVLink telemetry thread started")
        return True

    def _receive_loop(self):
        """Background thread that continuously receives and parses MAVLink messages.
        
        SAFETY: This loop is strictly READ-ONLY. It NEVER sends commands, RC overrides,
        mode changes, or any messages that could affect flight behaviour.
        """
        RAD2DEG = 57.29577951308232  # 180 / π

        while self._running:
            try:
                msg = self.mav_connection.recv_match(blocking=False)
                if msg is None:
                    time.sleep(0.01)
                    continue

                self._last_update_time = time.time()
                mtype = msg.get_type()

                with self._lock:
                    self._snapshot["msg_count"] += 1
                    self._snapshot["last_msg_type"] = mtype
                    msg_types = self._snapshot.setdefault("msg_types_seen", {})
                    msg_types[mtype] = msg_types.get(mtype, 0) + 1
                    self._raw_records.append(self._message_to_raw_record(msg, mtype))

                    # Parse GPS (GLOBAL_POSITION_INT)
                    if mtype == "GLOBAL_POSITION_INT":
                        self._snapshot["lat"] = msg.lat / 1e7
                        self._snapshot["lon"] = msg.lon / 1e7
                        self._snapshot["alt_abs"] = msg.alt / 1000.0
                        self._snapshot["alt_rel"] = msg.relative_alt / 1000.0  # mm to m
                        self._snapshot["vx"] = msg.vx / 100.0  # cm/s to m/s
                        self._snapshot["vy"] = msg.vy / 100.0
                        self._snapshot["vz"] = msg.vz / 100.0
                        self._snapshot["timestamp"] = time.time()
                        self._last_gps_time = time.time()

                    # Parse attitude (ATTITUDE)
                    elif mtype == "ATTITUDE":
                        self._snapshot["roll"] = msg.roll * RAD2DEG
                        self._snapshot["pitch"] = msg.pitch * RAD2DEG
                        self._snapshot["yaw"] = msg.yaw * RAD2DEG
                        self._snapshot["timestamp"] = time.time()

                    # Parse gimbal orientation (MOUNT_ORIENTATION)
                    elif mtype == "MOUNT_ORIENTATION":
                        self._set_gimbal_degrees(
                            roll=getattr(msg, "roll", None),
                            pitch=getattr(msg, "pitch", None),
                            yaw=getattr(msg, "yaw", None),
                            source=mtype,
                        )

                    # Parse legacy mount orientation (centidegrees)
                    elif mtype == "MOUNT_STATUS":
                        self._set_gimbal_degrees(
                            roll=getattr(msg, "pointing_a", 0) / 100.0,
                            pitch=getattr(msg, "pointing_b", 0) / 100.0,
                            yaw=getattr(msg, "pointing_c", 0) / 100.0,
                            source=mtype,
                        )

                    # Parse legacy gimbal report (radians)
                    elif mtype == "GIMBAL_REPORT":
                        self._set_gimbal_degrees(
                            roll=getattr(msg, "joint_roll", 0) * RAD2DEG,
                            pitch=getattr(msg, "joint_el", 0) * RAD2DEG,
                            yaw=getattr(msg, "joint_az", 0) * RAD2DEG,
                            source=mtype,
                        )

                    # Parse gimbal quaternion (GIMBAL_DEVICE_ATTITUDE_STATUS)
                    elif mtype == "GIMBAL_DEVICE_ATTITUDE_STATUS":
                        self._set_gimbal_from_quaternion(getattr(msg, "q", None), mtype)

                    # Some cameras publish the camera frustum pose directly
                    elif mtype in ("CAMERA_FOV_STATUS", "CAMERA_IMAGE_CAPTURED"):
                        self._set_gimbal_from_quaternion(getattr(msg, "q", None), mtype)

                    # Parse GPS status (GPS_RAW_INT)
                    elif mtype == "GPS_RAW_INT":
                        self._snapshot["satellites"] = msg.satellites_visible
                        self._snapshot["gps_fix"] = msg.fix_type
                        if hasattr(msg, "eph") and msg.eph is not None:
                            self._snapshot["hdop"] = msg.eph / 100.0  # HDOP in cm

            except Exception as e:
                logger.debug(f"MAVLink parse error: {e}")
                time.sleep(0.01)

    def snapshot(self) -> dict:
        """Return current telemetry snapshot."""
        with self._lock:
            snap = self._snapshot.copy()
            snap["msg_types_seen"] = dict(self._snapshot.get("msg_types_seen", {}))
            return snap

    def drain_raw_messages(self) -> list[dict]:
        """Return and clear raw MAVLink records accumulated since the last drain."""
        with self._lock:
            records = list(self._raw_records)
            self._raw_records.clear()
            return records

    def is_good_gps(self) -> bool:
        """Check if GPS is locked: 3D fix or better, sufficient satellites, and good HDOP."""
        with self._lock:
            fix = self._snapshot.get("gps_fix", 0)
            sats = self._snapshot.get("satellites", 0)
            hdop = self._snapshot.get("hdop", 999)
            return fix >= 3 and sats >= 6 and hdop <= self.hdop_limit

    def is_stale(self) -> bool:
        """Check if telemetry hasn't been updated recently."""
        return (time.time() - self._last_update_time) > self._stale_threshold_s

    def stop(self):
        """Stop receiving telemetry."""
        self._running = False
        if self.mav_thread:
            self.mav_thread.join(timeout=2)
        if self.mav_connection:
            self.mav_connection.close()
        logger.info("MAVLink stopped")


class CameraCapture:
    """Capture video from a local camera (index) or RTSP stream (URL).
    
    For RTSP streams, automatically drains the internal buffer to return
    the most recent frame (avoiding stale buffered frames from seconds ago).
    """

    def __init__(self, source: int | str, max_reconnect_attempts: int = 5,
                 backend: str = "auto"):
        self.source = source
        self.cap = None
        self._gst_capture = None
        self._is_rtsp = isinstance(source, str)
        self.backend = backend.lower()
        self._latest_frame = None
        self._latest_timestamp = 0.0
        self._latest_frame_id = 0
        self._frame_lock = Lock()
        self._max_reconnect = max_reconnect_attempts
        self._consecutive_failures = 0
        self._reader_thread = None
        self._reader_running = False

    def open(self) -> bool:
        """Open the camera or stream."""
        try:
            if isinstance(self.source, int):
                # Local camera by index
                logger.info(f"Opening camera index: {self.source}")
                self.cap = cv2.VideoCapture(self.source)
                # Request 1080p for local cameras
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
            else:
                # RTSP URL or file path
                logger.info(f"Opening RTSP stream: {self.source}")
                if self._open_gstreamer_if_available(str(self.source)):
                    return True
                if self.backend == "gstreamer":
                    return False
                self.cap = self._open_rtsp_capture(str(self.source))

            if not self.cap or not self.cap.isOpened():
                logger.error(f"Failed to open camera: {self.source}")
                return False

            w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            logger.info(f"Camera opened: {w}x{h}")
            self._consecutive_failures = 0
            return True
        except Exception as e:
            logger.error(f"Camera error: {e}")
            return False

    def _open_gstreamer_if_available(self, url: str) -> bool:
        if self.backend not in ("auto", "gstreamer", "gstreamer_stable", "gstreamer_low_latency"):
            return False
        if GStreamerCapture is None or not GStreamerCapture.available():
            if self.backend.startswith("gstreamer"):
                logger.error("GStreamer backend requested but not available")
            return False
        mode = "low_latency" if self.backend == "gstreamer_low_latency" else "stable"
        latency_ms = 100 if mode == "low_latency" else 500
        gst = GStreamerCapture(url, latency_ms=latency_ms, codec="auto", mode=mode)
        if gst.open():
            self._gst_capture = gst
            self._consecutive_failures = 0
            return True
        if getattr(gst, "last_error", ""):
            logger.error("GStreamer backend failed: %s", gst.last_error)
        if self.backend.startswith("gstreamer"):
            logger.error("GStreamer backend failed")
        return False

    def _open_rtsp_capture(self, url: str):
        """Open RTSP with transport fallback.

        Some DJI/controller links accept RTSP-over-UDP while others work better
        over RTSP-over-TCP. QGC hides this detail, so try both here.
        """
        original_options = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
        candidates = []
        if original_options:
            candidates.append(("custom", original_options))
        candidates.extend([
            ("tcp", "rtsp_transport;tcp|fflags;discardcorrupt|flags;low_delay"),
            ("udp", "rtsp_transport;udp|fflags;discardcorrupt|flags;low_delay"),
        ])

        seen = set()
        for transport, options in candidates:
            if options in seen:
                continue
            seen.add(options)
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = options
            logger.info("Trying RTSP transport: %s", transport)
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if cap and cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    logger.info("RTSP opened with %s transport", transport)
                    return cap
            if cap:
                cap.release()

        if original_options is None:
            os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
        else:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = original_options
        return None

    def start_reader(self) -> bool:
        """Continuously drain the camera/RTSP stream in the background."""
        if self._gst_capture is not None:
            return True
        if not self.cap or not self.cap.isOpened():
            return False
        if self._reader_thread and self._reader_thread.is_alive():
            return True
        self._reader_running = True
        self._reader_thread = Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        return True

    def _reader_loop(self):
        while self._reader_running:
            try:
                ret, frame = self.cap.read()
                if not ret:
                    self._consecutive_failures += 1
                    if self._is_rtsp and self._consecutive_failures <= self._max_reconnect:
                        self._reconnect()
                    else:
                        time.sleep(0.05)
                    continue
                self._consecutive_failures = 0
                with self._frame_lock:
                    self._latest_frame = frame.copy()
                    self._latest_timestamp = time.time()
                    self._latest_frame_id += 1
            except Exception as exc:
                logger.debug("Camera reader error: %s", exc)
                time.sleep(0.05)

    def latest_frame(self, max_age_s: float = 2.0):
        """Return the freshest decoded frame plus arrival timestamp and frame id."""
        if self._gst_capture is not None:
            frame, ts, frame_id = self._gst_capture.latest_frame(max_age_s=max_age_s)
            if frame is None and self._is_rtsp:
                stale = ts and (time.time() - ts) > max_age_s
                dead = (
                    getattr(self._gst_capture, "process", None) is not None
                    and self._gst_capture.process.poll() is not None
                )
                if stale or dead:
                    self._consecutive_failures += 1
                    if self._consecutive_failures <= self._max_reconnect:
                        logger.warning("GStreamer stream stale/dropped; reconnecting")
                        self._gst_capture.release()
                        self._gst_capture = None
                        if self._open_gstreamer_if_available(str(self.source)):
                            return self._gst_capture.latest_frame(max_age_s=max_age_s)
            return frame, ts, frame_id
        with self._frame_lock:
            if self._latest_frame is None:
                return None, 0.0, 0
            frame = self._latest_frame.copy()
            ts = self._latest_timestamp
            frame_id = self._latest_frame_id
        if max_age_s is not None and ts and (time.time() - ts) > max_age_s:
            return None, ts, frame_id
        return frame, ts, frame_id

    def grab_frame(self) -> np.ndarray | None:
        """Grab a frame from the camera (BGR, numpy array).
        
        For RTSP streams, drains the internal decode buffer first so
        the returned frame is the most recent one - not a stale buffered
        frame from seconds (or minutes) ago.
        """
        if self._gst_capture is not None:
            frame, _, _ = self._gst_capture.latest_frame(max_age_s=2.0)
            return frame
        if not self.cap or not self.cap.isOpened():
            return None

        try:
            # RTSP buffer drain: discard a few stale packets without blocking
            # for a full second on 30 fps streams.
            if self._is_rtsp:
                for _ in range(3):
                    if not self.cap.grab():
                        break
                ret, frame = self.cap.retrieve()
            else:
                ret, frame = self.cap.read()

            if not ret:
                self._consecutive_failures += 1
                if self._is_rtsp and self._consecutive_failures <= self._max_reconnect:
                    if self._reconnect():
                        return self.grab_frame()
                logger.warning(f"Frame grab failed (attempt {self._consecutive_failures})")
                return None

            self._consecutive_failures = 0
            with self._frame_lock:
                self._latest_frame = frame.copy()
                self._latest_timestamp = time.time()
                self._latest_frame_id += 1
            return frame
        except Exception as e:
            logger.debug(f"Frame grab error: {e}")
            return None

    def _reconnect(self) -> bool:
        """Attempt to reopen RTSP stream after connection loss."""
        logger.warning("Stream dropped. Attempting reconnect (%d/%d)…",
                       self._consecutive_failures, self._max_reconnect)
        if self._reader_thread and current_thread() is self._reader_thread:
            if self.cap:
                self.cap.release()
                self.cap = None
        else:
            self.release()
        time.sleep(2.0)  # brief pause before retry
        return self.open()

    def release(self):
        """Release the camera."""
        if self._gst_capture is not None:
            self._gst_capture.release()
            self._gst_capture = None
        self._reader_running = False
        if self._reader_thread and current_thread() is not self._reader_thread:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None
        if self.cap:
            self.cap.release()
            self.cap = None
            logger.info("Camera released")


def build_xmp(telem: dict, attitude_fallback: str = "stabilized") -> str:
    """Build a DJI-compatible XMP XML string from telemetry data.
    
    The mapper's PoseExtractor.get_meta() searches for the `drone-dji:` namespace
    and extracts fields by name, so the attribute names here must match exactly.
    
    Gimbal angles:
      - If gimbal data is available, use real gimbal roll/pitch/yaw
      - Otherwise use either aircraft attitude or fixed nadir fallback
    """
    # Resolve gimbal angles: prefer actual gimbal data over aircraft body
    if telem.get("has_gimbal") and telem.get("gimbal_yaw") is not None:
        gimbal_roll = telem["gimbal_roll"]
        gimbal_pitch = telem["gimbal_pitch"]
        gimbal_yaw = telem["gimbal_yaw"]
    elif attitude_fallback == "aircraft":
        # Body-follow fallback for streams without gimbal telemetry. This treats
        # the camera as looking down relative to the aircraft body, so aircraft
        # roll/pitch tilt the optical axis during sideways or accelerating flight.
        gimbal_roll = telem.get("roll", 0.0)
        gimbal_pitch = -90.0 + telem.get("pitch", 0.0)
        gimbal_yaw = telem.get("yaw", 0.0)
    else:
        # Fixed nadir mount fallback:
        #   roll = 0 (camera is level even if aircraft banks)
        #   pitch = -90 (pointing straight down)
        #   yaw = aircraft heading (camera faces wherever nose points)
        gimbal_roll = 0.0
        gimbal_pitch = -90.0
        gimbal_yaw = telem.get("yaw", 0)

    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"'
        ' xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/"'
        ' xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:RDF>'
        '<rdf:Description rdf:about=""'
        f' drone-dji:AbsoluteAltitude="{telem.get("alt_abs", 0):.6f}"'
        f' drone-dji:RelativeAltitude="{telem.get("alt_rel", 0):.6f}"'
        f' drone-dji:GpsLatitude="{telem.get("lat", 0):.8f}"'
        f' drone-dji:GpsLongitude="{telem.get("lon", 0):.8f}"'
        f' drone-dji:GimbalPitchDegree="{gimbal_pitch:.2f}"'
        f' drone-dji:GimbalYawDegree="{gimbal_yaw:.2f}"'
        f' drone-dji:GimbalRollDegree="{gimbal_roll:.2f}"'
        '/>'
        '</rdf:RDF>'
        '</x:xmpmeta>'
    )


def inject_xmp(jpeg_bytes: bytes, xmp_str: str) -> bytes:
    """Inject XMP metadata into a JPEG APP1 segment immediately after SOI."""
    soi = b"\xff\xd8"
    app1_marker = b"\xff\xe1"
    namespace = b"http://ns.adobe.com/xap/1.0/\x00"

    if jpeg_bytes[:2] != soi:
        raise ValueError("Not a valid JPEG (missing SOI marker)")

    xmp_bytes = xmp_str.encode("utf-8")
    app1_length = 2 + len(namespace) + len(xmp_bytes)
    if app1_length > 0xFFFF:
        raise ValueError("XMP payload too large for JPEG APP1 segment")

    app1_segment = app1_marker + struct.pack(">H", app1_length) + namespace + xmp_bytes
    return soi + app1_segment + jpeg_bytes[2:]


def frame_to_tagged_jpeg(
    frame: np.ndarray,
    telemetry_snap: dict,
    attitude_fallback: str = "stabilized",
) -> bytes:
    """Encode a frame as JPEG and embed telemetry data as DJI XMP metadata.
    
    Args:
        frame: BGR numpy array
        telemetry_snap: dict with keys: lat, lon, alt_rel, alt_abs, yaw, roll, pitch,
                       gimbal_roll, gimbal_pitch, gimbal_yaw, has_gimbal
    
    Returns:
        JPEG bytes with embedded DJI XMP metadata.
    """
    try:
        # Encode as JPEG
        ret, jpeg_data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ret:
            raise ValueError("Failed to encode JPEG")
        
        xmp_str = build_xmp(telemetry_snap, attitude_fallback=attitude_fallback)
        return inject_xmp(jpeg_data.tobytes(), xmp_str)

    except Exception as e:
        logger.debug(f"XMP embedding failed: {e}; returning plain JPEG")
        ret, jpeg_data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return jpeg_data.tobytes() if ret else b''


if __name__ == "__main__":
    # Simple test
    logging.basicConfig(level=logging.INFO)
    
    print("Testing MAVLink connection (auto-detect)...")
    telem = MAVLinkTelemetry()
    if telem.connect():
        if telem.start():
            print("Reading telemetry for 5 seconds...")
            for i in range(50):
                snap = telem.snapshot()
                print(f"  GPS: ({snap['lat']:.6f}, {snap['lon']:.6f}) Alt={snap['alt_rel']:.1f}m Sats={snap['satellites']}")
                time.sleep(0.1)
            telem.stop()
            print("Test passed!")
    else:
        print("MAVLink connection failed (this is OK if no autopilot connected)")
