"""
Optional GStreamer RTSP capture backend.

This module is intentionally dependency-optional. On Windows, the standard
`opencv-python` wheel usually has no GStreamer support, so this backend uses
PyGObject (`gi.repository.Gst`) directly when the GStreamer runtime is installed.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from threading import Lock, Thread

import numpy as np

logger = logging.getLogger(__name__)


def _gst_launch_path() -> str | None:
    found = shutil.which("gst-launch-1.0")
    if found:
        return found
    candidates = [
        r"C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe",
        r"C:\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _gst_root_from_launch(gst_launch: str | None) -> str | None:
    if not gst_launch:
        return None
    # ...\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe
    return os.path.dirname(os.path.dirname(gst_launch))


def _gst_env() -> dict:
    env = os.environ.copy()
    gst_launch = _gst_launch_path()
    root = _gst_root_from_launch(gst_launch)
    if root:
        bin_dir = os.path.join(root, "bin")
        scanner = os.path.join(root, "libexec", "gstreamer-1.0", "gst-plugin-scanner.exe")
        plugin_dir = os.path.join(root, "lib", "gstreamer-1.0")
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        if os.path.isfile(scanner):
            env["GST_PLUGIN_SCANNER"] = scanner
        if os.path.isdir(plugin_dir):
            env["GST_PLUGIN_PATH"] = plugin_dir
    return env

try:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
except Exception:  # pragma: no cover - optional system dependency
    Gst = None


class GStreamerCapture:
    """Low-latency RTSP reader using GStreamer appsink."""

    def __init__(self, url: str, latency_ms: int = 400, codec: str = "auto",
                 width: int = 1280, height: int = 720, mode: str = "stable"):
        self.url = url
        self.latency_ms = int(latency_ms)
        self.codec = codec.lower()
        self.width = int(width)
        self.height = int(height)
        self.mode = mode.lower()
        self.pipeline = None
        self.appsink = None
        self.process = None
        self._reader_thread = None
        self._running = False
        self._latest_frame = None
        self._latest_timestamp = 0.0
        self._latest_frame_id = 0
        self._lock = Lock()
        self.last_error = ""

    @staticmethod
    def available() -> bool:
        return Gst is not None or _gst_launch_path() is not None

    def open(self) -> bool:
        if Gst is None and _gst_launch_path() is not None:
            return self._open_gst_launch()
        if Gst is None:
            logger.warning("GStreamer/PyGObject is not available")
            return False
        Gst.init(None)

        codecs = [self.codec] if self.codec in ("h264", "h265") else ["h265", "h264"]
        for codec in codecs:
            pipe = self._pipeline_string(codec)
            logger.info("Trying GStreamer RTSP pipeline (%s)", codec)
            try:
                pipeline = Gst.parse_launch(pipe)
                appsink = pipeline.get_by_name("sink")
                appsink.connect("new-sample", self._on_sample)
                pipeline.set_state(Gst.State.PLAYING)
                if self._wait_for_first_frame(pipeline):
                    self.pipeline = pipeline
                    self.appsink = appsink
                    logger.info("GStreamer RTSP opened with %s", codec)
                    return True
                pipeline.set_state(Gst.State.NULL)
            except Exception as exc:
                logger.warning("GStreamer pipeline failed (%s): %s", codec, exc)
        return False

    def _open_gst_launch(self) -> bool:
        codecs = [self.codec] if self.codec in ("h264", "h265") else ["auto", "h265", "h264"]
        transports = ("tcp", "udp") if self.mode == "stable" else ("udp", "tcp")
        for codec in codecs:
            for transport in transports:
                cmd = self._gst_launch_command(codec, transport)
                logger.info("Trying gst-launch RTSP pipeline (%s/%s)", codec, transport)
                try:
                    self.process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        stdin=subprocess.DEVNULL,
                        env=_gst_env(),
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                    )
                    self._running = True
                    self._reader_thread = Thread(target=self._read_raw_frames, daemon=True)
                    self._reader_thread.start()
                    if self._wait_for_subprocess_frame():
                        logger.info("gst-launch RTSP opened with %s/%s", codec, transport)
                        return True
                    self.last_error = self._collect_stderr_tail() or "no frame before timeout"
                    if self.last_error:
                        logger.warning(
                            "gst-launch pipeline produced no frame (%s/%s): %s",
                            codec,
                            transport,
                            self.last_error,
                        )
                except Exception as exc:
                    self.last_error = str(exc)
                    logger.warning("gst-launch pipeline failed (%s/%s): %s", codec, transport, exc)
                self.release()
        return False

    def _gst_launch_command(self, codec: str, transport: str) -> list[str]:
        stable = self.mode == "stable"
        common_head = [
            _gst_launch_path() or "gst-launch-1.0",
            "-q",
            "rtspsrc",
            f"location={self.url}",
            f"protocols={transport}",
            f"latency={self.latency_ms}",
            f"drop-on-latency={'false' if stable else 'true'}",
            f"do-retransmission={'true' if stable else 'false'}",
            "!",
            "queue",
            f"leaky={'no' if stable else 'downstream'}",
            f"max-size-buffers={'0' if stable else '1'}",
            f"max-size-time={'2000000000' if stable else '0'}",
            "max-size-bytes=0",
            "!",
        ]
        common_tail = [
            "queue",
            "leaky=downstream",
            "max-size-buffers=2",
            "max-size-time=0",
            "max-size-bytes=0",
            "!",
            "videoconvert",
            "!",
            "videoscale",
            "!",
            f"video/x-raw,format=BGR,width={self.width},height={self.height}",
            "!",
            "queue",
            "leaky=downstream",
            "max-size-buffers=1",
            "max-size-time=0",
            "max-size-bytes=0",
            "!",
            "fdsink",
            "fd=1",
            "sync=false",
        ]
        if codec == "auto":
            return common_head + ["decodebin", "!"] + common_tail
        if codec == "h265":
            depay = "rtph265depay"
            parse = "h265parse"
            decode = "avdec_h265"
        else:
            depay = "rtph264depay"
            parse = "h264parse"
            decode = "avdec_h264"
        return common_head + [
            depay,
            "!",
            parse,
            "!",
            decode,
            "!",
        ] + common_tail

    def _collect_stderr_tail(self) -> str:
        if not self.process or not self.process.stderr:
            return ""
        try:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=1)
            data = self.process.stderr.read() or b""
            text = data.decode("utf-8", errors="ignore")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            lines = [
                line for line in lines
                if "gstpython.dll" not in line
                and "dumpbin -dependents" not in line
                and "third-party GUIs" not in line
                and "External plugin loader failed" not in line
            ]
            return " | ".join(lines[-6:])
        except Exception:
            return ""

    def _read_raw_frames(self):
        frame_bytes = self.width * self.height * 3
        while self._running and self.process and self.process.stdout:
            data = self.process.stdout.read(frame_bytes)
            if not data or len(data) < frame_bytes:
                break
            frame = np.frombuffer(data, dtype=np.uint8).reshape((self.height, self.width, 3)).copy()
            with self._lock:
                self._latest_frame = frame
                self._latest_timestamp = time.time()
                self._latest_frame_id += 1
        self._running = False

    def _wait_for_subprocess_frame(self, timeout_s: float = 5.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.process and self.process.poll() is not None:
                return False
            with self._lock:
                if self._latest_frame is not None:
                    return True
            time.sleep(0.05)
        return False

    def _pipeline_string(self, codec: str) -> str:
        if codec == "h265":
            depay = "rtph265depay ! h265parse"
            decoders = "d3d11h265dec ! d3d11download ! videoconvert"
            fallback = "avdec_h265 ! videoconvert"
        else:
            depay = "rtph264depay ! h264parse"
            decoders = "d3d11h264dec ! d3d11download ! videoconvert"
            fallback = "avdec_h264 ! videoconvert"

        # Try hardware decode first via decodebin-like fallback is awkward in a
        # static string, so use avdec if Direct3D decode is unavailable.
        # The caller retries h264/h265 separately.
        return (
            f'rtspsrc location="{self.url}" protocols=tcp latency={self.latency_ms} '
            f"drop-on-latency=true do-retransmission=false ! "
            "queue leaky=downstream max-size-buffers=1 max-size-time=0 max-size-bytes=0 ! "
            f"{depay} ! queue leaky=downstream max-size-buffers=1 ! "
            f"{fallback} ! video/x-raw,format=BGR ! "
            "appsink name=sink emit-signals=true sync=false max-buffers=1 drop=true"
        )

    def _wait_for_first_frame(self, pipeline, timeout_s: float = 5.0) -> bool:
        deadline = time.time() + timeout_s
        bus = pipeline.get_bus()
        while time.time() < deadline:
            with self._lock:
                if self._latest_frame is not None:
                    return True
            msg = bus.timed_pop_filtered(
                100_000_000,
                Gst.MessageType.ERROR | Gst.MessageType.EOS,
            )
            if msg:
                if msg.type == Gst.MessageType.ERROR:
                    err, debug = msg.parse_error()
                    logger.warning("GStreamer bus error: %s (%s)", err, debug)
                return False
        return False

    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR
        buf = sample.get_buffer()
        caps = sample.get_caps()
        info = caps.get_structure(0)
        width = info.get_value("width")
        height = info.get_value("height")
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.ERROR
        try:
            frame = np.frombuffer(mapinfo.data, dtype=np.uint8).reshape((height, width, 3)).copy()
            with self._lock:
                self._latest_frame = frame
                self._latest_timestamp = time.time()
                self._latest_frame_id += 1
        finally:
            buf.unmap(mapinfo)
        return Gst.FlowReturn.OK

    def latest_frame(self, max_age_s: float = 2.0):
        with self._lock:
            if self._latest_frame is None:
                return None, 0.0, 0
            frame = self._latest_frame.copy()
            ts = self._latest_timestamp
            frame_id = self._latest_frame_id
        if max_age_s is not None and ts and (time.time() - ts) > max_age_s:
            return None, ts, frame_id
        return frame, ts, frame_id

    def release(self):
        self._running = False
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2)
            self._reader_thread = None
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        self.appsink = None
