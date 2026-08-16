"""
SkyForge GCS - Ground Control Station
======================================
Professional PyQt6 desktop application for real-time aerial orthomosaic
mapping with satellite underlay, MAVLink telemetry, and live camera feed.

Usage:
    python gcs_app.py                     # launch GUI
    python gcs_app.py --mavlink           # auto-connect MAVLink on start
    python gcs_app.py --simulate          # auto-start simulation on launch
"""

import sys, os, time, glob, argparse, math, logging, traceback, threading, json
from collections import deque
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

import cv2
import numpy as np

from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, pyqtSlot, QSize, QRectF, QPointF,
    QElapsedTimer, QMutex, QMutexLocker, QSettings, QByteArray,
)
from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QFont, QPen, QBrush,
    QLinearGradient, QRadialGradient, QIcon, QAction, QKeySequence,
    QPalette, QFontDatabase, QTransform, QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QComboBox, QSlider, QSpinBox,
    QDoubleSpinBox, QCheckBox, QFileDialog, QStatusBar, QToolBar,
    QDockWidget, QSplitter, QFrame, QGroupBox, QProgressBar,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QSizePolicy, QTabWidget, QTextEdit, QStackedWidget, QToolButton,
    QSpacerItem, QScrollArea, QMessageBox, QSplashScreen,
    QInputDialog, QLineEdit, QProgressDialog,
)

# --- Project imports ---
sys.path.insert(0, os.path.dirname(__file__))
from backend.mapper_service import MapperService, CAMERA_PROFILES
from backend.mission_manager import MissionManager
from config_manager import ConfigManager, SKYFORGE_LOG_DIR, SKYFORGE_DATA_DIR

# ── Version - single source of truth from version.txt ──
def _read_version() -> str:
    vfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.txt")
    try:
        return Path(vfile).read_text(encoding="utf-8").strip()
    except Exception:
        return "1.0.0"

__version__ = _read_version()

# ── Logging - file-based with rotation ──
def _setup_logging():
    """Configure file + console logging for the entire application."""
    os.makedirs(SKYFORGE_LOG_DIR, exist_ok=True)
    log_file = os.path.join(
        SKYFORGE_LOG_DIR,
        f"skyforge_{datetime.now().strftime('%Y%m%d')}.log"
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # File handler (rotated, 5 MB × 5 backups)
    fh = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(fh)

    # Console handler (INFO only, for dev use)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(ch)

    logging.info(f"SkyForge GCS v{__version__} - logging to {log_file}")

logger = logging.getLogger("SkyForge")

# ── Global crash handler ──
def _global_exception_handler(exc_type, exc_value, exc_tb):
    """Catch unhandled exceptions, log them, and show a crash dialog."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical(f"Unhandled exception:\n{tb_text}")
    # Write crash file
    try:
        crash_file = os.path.join(
            SKYFORGE_LOG_DIR,
            f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write(f"SkyForge GCS v{__version__} - Crash Report\n")
            f.write(f"Time: {datetime.now().isoformat()}\n")
            f.write(f"{'=' * 60}\n")
            f.write(tb_text)
    except Exception:
        pass
    # Show dialog if QApplication exists
    app = QApplication.instance()
    if app:
        QMessageBox.critical(
            None, "SkyForge GCS - Crash",
            f"An unexpected error occurred.\n\n"
            f"{exc_type.__name__}: {exc_value}\n\n"
            f"A crash log has been saved to:\n{SKYFORGE_LOG_DIR}\n\n"
            f"Please report this to the development team.",
        )

def _thread_exception_handler(args):
    """Handle uncaught exceptions in threads."""
    logger.critical(
        f"Unhandled exception in thread '{args.thread.name}':\n"
        + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    )

# ══════════════════════════════════════════════════════════════════════
#  THEME MANAGER - Dark/Light switchable palette
# ══════════════════════════════════════════════════════════════════════

class ThemeManager:
    """Manages dark/light theme for the entire application."""
    
    DARK_THEME = {
        'bg':           "#0a0e14",
        'panel':        "#111720",
        'panel_light':  "#1a2230",
        'border':       "#263040",
        'accent':       "#00d4ff",
        'accent_dim':   "#007a99",
        'green':        "#00ff88",
        'yellow':       "#ffd600",
        'red':          "#ff3355",
        'orange':       "#ff8800",
        'text':         "#e0e8f0",
        'text_dim':     "#8090a0",
        'text_bright':  "#ffffff",
    }
    
    LIGHT_THEME = {
        'bg':           "#f5f5f5",
        'panel':        "#ffffff",
        'panel_light':  "#f8f8f8",
        'border':       "#d0d0d0",
        'accent':       "#0078d4",
        'accent_dim':   "#80b8e8",
        'green':        "#107c10",
        'yellow':       "#ffc800",
        'red':          "#d13438",
        'orange':       "#d83b01",
        'text':         "#201f1e",
        'text_dim':     "#626262",
        'text_bright':  "#000000",
    }
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._theme = 'dark'
        return cls._instance
    
    @staticmethod
    def get():
        return ThemeManager()
    
    def set_theme(self, theme_name: str):
        """Set current theme ('dark' or 'light')."""
        if theme_name in ['dark', 'light']:
            self._theme = theme_name
    
    def get_theme(self) -> str:
        return self._theme
    
    def colors(self) -> dict:
        """Get current theme colors."""
        return self.LIGHT_THEME if self._theme == 'light' else self.DARK_THEME
    
    def get_color(self, key: str) -> str:
        """Get a specific color from current theme."""
        return self.colors().get(key, "#ffffff")

# Global theme instance
_theme = ThemeManager()

# Convenience accessors for backward compatibility
def _get_color(key: str) -> str:
    return _theme.get_color(key)

_colors = _theme.colors()
C_BG           = _colors['bg']
C_PANEL        = _colors['panel']
C_PANEL_LIGHT  = _colors['panel_light']
C_BORDER       = _colors['border']
C_ACCENT       = _colors['accent']
C_ACCENT_DIM   = _colors['accent_dim']
C_GREEN        = _colors['green']
C_YELLOW       = _colors['yellow']
C_RED          = _colors['red']
C_ORANGE       = _colors['orange']
C_TEXT         = _colors['text']
C_TEXT_DIM     = _colors['text_dim']
C_TEXT_BRIGHT  = _colors['text_bright']

DARK_STYLESHEET = f"""
QMainWindow {{
    background: {C_BG};
}}
QWidget {{
    background: transparent;
    color: {C_TEXT};
    font-family: "Segoe UI", "Inter", "Roboto", sans-serif;
    font-size: 12px;
}}
QDockWidget {{
    titlebar-close-icon: none;
    font-weight: bold;
    font-size: 11px;
    color: {C_ACCENT};
    border: 1px solid {C_BORDER};
}}
QDockWidget::title {{
    background: {C_PANEL};
    padding: 6px 10px;
    border-bottom: 1px solid {C_BORDER};
}}
QGroupBox {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 12px 8px 8px 8px;
    font-weight: bold;
    font-size: 11px;
    color: {C_ACCENT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}
QPushButton {{
    background: {C_PANEL_LIGHT};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 6px 16px;
    color: {C_TEXT};
    font-weight: 600;
    min-height: 28px;
}}
QPushButton:hover {{
    background: {C_ACCENT_DIM};
    border-color: {C_ACCENT};
    color: {C_TEXT_BRIGHT};
}}
QPushButton:pressed {{
    background: {C_ACCENT};
    color: {C_BG};
}}
QPushButton:disabled {{
    background: {C_PANEL};
    color: {C_TEXT_DIM};
    border-color: {C_PANEL};
}}
QPushButton#accentBtn {{
    background: {C_ACCENT_DIM};
    border-color: {C_ACCENT};
    color: {C_TEXT_BRIGHT};
}}
QPushButton#accentBtn:hover {{
    background: {C_ACCENT};
    color: {C_BG};
}}
QPushButton#dangerBtn {{
    background: #331122;
    border-color: {C_RED};
    color: {C_RED};
}}
QPushButton#dangerBtn:hover {{
    background: {C_RED};
    color: {C_TEXT_BRIGHT};
}}
QComboBox {{
    background: {C_PANEL_LIGHT};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    padding: 4px 10px;
    min-height: 26px;
}}
QComboBox QAbstractItemView {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
    selection-background-color: {C_ACCENT_DIM};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {C_BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {C_ACCENT};
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {C_ACCENT_DIM};
    border-radius: 2px;
}}
QProgressBar {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    text-align: center;
    color: {C_TEXT};
    height: 18px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {C_ACCENT_DIM}, stop:1 {C_ACCENT});
    border-radius: 2px;
}}
QCheckBox {{
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    background: {C_PANEL};
}}
QCheckBox::indicator:checked {{
    background: {C_ACCENT};
    border-color: {C_ACCENT};
}}
QTabWidget::pane {{
    border: 1px solid {C_BORDER};
    border-top: none;
    background: {C_PANEL};
}}
QTabBar::tab {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
    border-bottom: none;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: {C_TEXT_DIM};
}}
QTabBar::tab:selected {{
    background: {C_PANEL_LIGHT};
    color: {C_ACCENT};
    border-bottom: 2px solid {C_ACCENT};
}}
QScrollBar:vertical {{
    background: {C_PANEL};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER};
    min-height: 20px;
    border-radius: 4px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QStatusBar {{
    background: {C_PANEL};
    border-top: 1px solid {C_BORDER};
    color: {C_TEXT_DIM};
    font-size: 11px;
}}
QToolBar {{
    background: {C_PANEL};
    border-bottom: 1px solid {C_BORDER};
    spacing: 4px;
    padding: 2px 6px;
}}
QLabel#hudValue {{
    font-family: "Consolas", "JetBrains Mono", monospace;
    font-size: 20px;
    font-weight: bold;
    color: {C_TEXT_BRIGHT};
}}
QLabel#hudLabel {{
    font-size: 11px;
    color: {C_TEXT_DIM};
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QLabel#hudUnit {{
    font-size: 11px;
    color: {C_ACCENT_DIM};
}}
QLabel#sectionTitle {{
    font-size: 12px;
    font-weight: bold;
    color: {C_ACCENT};
    padding: 4px 0;
}}
QTextEdit {{
    background: {C_PANEL};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    color: {C_TEXT_DIM};
    font-family: "Consolas", "JetBrains Mono", monospace;
    font-size: 11px;
    padding: 4px;
}}
"""


# ══════════════════════════════════════════════════════════════════════
#  WORKER THREADS
# ══════════════════════════════════════════════════════════════════════

def _is_invalid_video_frame(frame: np.ndarray) -> bool:
    """Detect flat gray decoder placeholder frames from unstable RTSP streams."""
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        return (
            (float(gray.std()) < 6.0 and float(hsv[:, :, 1].mean()) < 8.0)
            or sharpness < 18.0
        )
    except Exception:
        return False


def _frame_signature(frame: np.ndarray) -> np.ndarray | None:
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
    except Exception:
        return None


def _frame_signature_diff(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 999.0
    return float(cv2.absdiff(a, b).mean())


def _frame_motion_px(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 0.0
    try:
        a32 = np.float32(a)
        b32 = np.float32(b)
        shift, response = cv2.phaseCorrelate(a32, b32)
        if response < 0.05:
            return 0.0
        return float(math.hypot(shift[0], shift[1]))
    except Exception:
        return 0.0


def _gps_distance_m(a: dict | None, b: dict | None) -> float:
    if not a or not b:
        return 0.0
    lat1, lon1 = float(a.get("lat", 0.0)), float(a.get("lon", 0.0))
    lat2, lon2 = float(b.get("lat", 0.0)), float(b.get("lon", 0.0))
    if not lat1 or not lon1 or not lat2 or not lon2:
        return 0.0
    r = 6378137.0
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) * 0.5)) * r
    y = math.radians(lat2 - lat1) * r
    return math.hypot(x, y)


class MapProcessorWorker(QThread):
    """Background worker that processes images and emits results."""
    image_processed = pyqtSignal(dict)       # result dict from process_image
    map_rendered = pyqtSignal(np.ndarray)     # BGR map image
    error_occurred = pyqtSignal(str)
    processing_time = pyqtSignal(float)       # process ms
    render_time = pyqtSignal(float)           # render ms

    def __init__(self, service: MapperService, parent=None):
        super().__init__(parent)
        self._service = service
        self._queue = []          # list of (img_bytes, source_name)
        self._mutex = QMutex()
        self._running = True

    def enqueue(self, img_bytes: bytes, source: str = ""):
        with QMutexLocker(self._mutex):
            if source.startswith("mavlink_"):
                self._queue = [
                    item for item in self._queue
                    if not item[1].startswith("mavlink_")
                ]
            self._queue.append((img_bytes, source))

    def clear_queue(self) -> int:
        with QMutexLocker(self._mutex):
            count = len(self._queue)
            self._queue.clear()
            return count

    @property
    def queue_size(self) -> int:
        with QMutexLocker(self._mutex):
            return len(self._queue)

    def stop(self):
        self._running = False
        self.wait(5000)

    def run(self):
        while self._running:
            item = None
            with QMutexLocker(self._mutex):
                if self._queue:
                    item = self._queue.pop(0)
            if item is None:
                self.msleep(20)
                continue
            img_bytes, source = item
            try:
                t0 = time.perf_counter()
                result = self._service.process_image(img_bytes)
                dt_process = (time.perf_counter() - t0) * 1000
                self.processing_time.emit(dt_process)
                result["source"] = source
                self.image_processed.emit(result)
                # Render map (timed)
                t1 = time.perf_counter()
                map_img = self._service.mapper.render_map(
                    0,
                    show_flight_path=self._service.show_flight_path,
                    satellite_bg=self._render_satellite_bg(),
                )
                dt_render = (time.perf_counter() - t1) * 1000
                self.render_time.emit(dt_render)
                if map_img is not None:
                    self.map_rendered.emit(map_img)
            except Exception as e:
                self.error_occurred.emit(str(e))

    def _render_satellite_bg(self):
        """Get satellite background if available."""
        try:
            if self._service.satellite_provider and self._service.show_satellite:
                tile_keys = list(self._service.mapper.tiles.keys())
                if tile_keys:
                    return self._service.satellite_provider.get_background_for_render(
                        tile_keys,
                        self._service.mapper.tile_size,
                        self._service.mapper.resolution,
                    )
        except Exception:
            pass
        return None


class SimulationWorker(QThread):
    """Feeds images from a folder at a configurable rate."""
    frame_ready = pyqtSignal(bytes, str)    # img_bytes, filename
    progress = pyqtSignal(int, int)          # current, total
    finished_sim = pyqtSignal()

    def __init__(self, folder: str, interval_ms: int = 300, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.interval_ms = interval_ms
        self._running = True

    def stop(self):
        self._running = False
        self.wait(3000)

    def run(self):
        manifest_path = os.path.join(self.folder, "frame_manifest.jsonl")
        files = []
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as mf:
                    for line in mf:
                        rec = json.loads(line)
                        filename = rec.get("filename")
                        if filename:
                            fp = os.path.join(self.folder, filename)
                            if os.path.isfile(fp):
                                files.append(fp)
            except Exception:
                files = []
        if not files:
            patterns = ["*.jpg", "*.jpeg", "*.JPG", "*.JPEG"]
            for p in patterns:
                files.extend(glob.glob(os.path.join(self.folder, p)))
            files = sorted(set(files))
        total = len(files)
        if total == 0:
            self.finished_sim.emit()
            return
        for i, fp in enumerate(files):
            if not self._running:
                break
            try:
                with open(fp, "rb") as f:
                    data = f.read()
                self.frame_ready.emit(data, os.path.basename(fp))
                self.progress.emit(i + 1, total)
            except Exception:
                pass
            self.msleep(self.interval_ms)
        self.finished_sim.emit()


class MAVLinkWorker(QThread):
    """Bridges MAVLink telemetry + camera into the processing pipeline."""
    frame_ready = pyqtSignal(bytes, str)
    telemetry_update = pyqtSignal(dict)
    raw_mavlink_messages = pyqtSignal(list)
    camera_frame = pyqtSignal(np.ndarray)
    status_message = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)

    def __init__(self, connection_str: str = "", camera_source=0,
                 interval_ms: int = 1000, allow_low_altitude: bool = False,
                 video_delay_ms: int = 1000,
                 video_backend: str = "auto",
                 attitude_fallback: str = "stabilized",
                 parent=None):
        super().__init__(parent)
        self.connection_str = connection_str
        self.camera_source = camera_source
        self.interval_ms = interval_ms
        self.allow_low_altitude = allow_low_altitude
        self.video_delay_ms = max(0, int(video_delay_ms))
        self.video_backend = video_backend
        self.attitude_fallback = attitude_fallback
        self._running = True

    def stop(self):
        self._running = False
        self.wait(5000)

    def run(self):
        try:
            from mavlink_feed import MAVLinkTelemetry, CameraCapture, frame_to_tagged_jpeg
        except ImportError:
            self.status_message.emit("ERROR: mavlink_feed.py not found")
            return

        telem = MAVLinkTelemetry()

        # ── Connect with auto-retry ──
        MAX_RETRIES = 5
        RETRY_DELAY_S = 3
        connected = False
        for attempt in range(1, MAX_RETRIES + 1):
            if not self._running:
                return
            self.status_message.emit(f"Connecting to drone (attempt {attempt}/{MAX_RETRIES})...")
            if telem.connect(self.connection_str or None):
                if telem.start():
                    connected = True
                    break
            self.status_message.emit(f"Drone link failed - retrying in {RETRY_DELAY_S}s")
            self.msleep(RETRY_DELAY_S * 1000)

        if not connected:
            self.status_message.emit("Drone link FAILED after all retries")
            self.connection_changed.emit(False)
            return

        self.status_message.emit("Drone link connected ✓")
        self.connection_changed.emit(True)

        cam = None
        cam_ok = False
        if self.camera_source is not None:
            cam = CameraCapture(self.camera_source, backend=self.video_backend)
            cam_ok = cam.open()
            if cam_ok:
                self.status_message.emit("Camera opened ✓")
                if cam.start_reader():
                    self.status_message.emit("Camera reader started ✓")
            else:
                self.status_message.emit("Camera FAILED - telemetry-only mode")
        else:
            self.status_message.emit("Camera disabled - telemetry-only mode")

        frame_num = 0
        heartbeat_timeout_s = 10
        last_telem_time = time.time()
        heartbeat_warned = False
        _last_lat = _last_lon = _last_alt = None
        _stale_count = 0
        _telem_history = deque(maxlen=600)
        _last_accepted_sig = None
        _last_accepted_snap = None
        _last_sampled_frame_id = 0
        _next_capture_time = 0.0
        _next_telem_emit_time = 0.0
        MIN_ALTITUDE = 2.0  # metres - skip frames below this AGL

        def remember_snapshot(s: dict) -> dict:
            ss = s.copy()
            ss["_wall_time"] = time.time()
            _telem_history.append(ss)
            return ss

        def public_snapshot(s: dict) -> dict:
            return {k: v for k, v in s.items() if not k.startswith("_")}

        def snapshot_at(frame_wall_time: float) -> dict:
            latest = remember_snapshot(telem.snapshot())
            if self.video_delay_ms <= 0 or not _telem_history:
                return public_snapshot(latest)
            target = frame_wall_time - (self.video_delay_ms / 1000.0)
            snap_at_time = min(
                _telem_history,
                key=lambda ss: abs(ss.get("_wall_time", target) - target),
            )
            return public_snapshot(snap_at_time)

        while self._running:
            snap = remember_snapshot(telem.snapshot())
            raw_records = telem.drain_raw_messages()
            if raw_records:
                self.raw_mavlink_messages.emit(raw_records)
            # Heartbeat watchdog
            if snap.get('lat', 0) != 0 or snap.get('lon', 0) != 0:
                last_telem_time = time.time()
                if heartbeat_warned:
                    self.status_message.emit("Drone link restored ✓")
                    self.connection_changed.emit(True)
                    heartbeat_warned = False
            elif time.time() - last_telem_time > heartbeat_timeout_s and not heartbeat_warned:
                self.status_message.emit("⚠ Drone link lost - waiting for data")
                self.connection_changed.emit(False)
                heartbeat_warned = True

            now = time.time()
            if now >= _next_telem_emit_time:
                self.telemetry_update.emit(public_snapshot(snap))
                _next_telem_emit_time = now + 0.5

            if cam_ok and cam is not None:
                if now < _next_capture_time:
                    self.msleep(50)
                    continue
                _next_capture_time = now + (self.interval_ms / 1000.0)

                frame, frame_ts, frame_id = cam.latest_frame(
                    max_age_s=max(2.0, (self.interval_ms / 1000.0) * 2.0)
                )
                if frame_id == _last_sampled_frame_id:
                    self.status_message.emit("Waiting for fresh camera frame")
                    self.msleep(50)
                    continue
                _last_sampled_frame_id = frame_id
                if frame is not None:
                    snap = snapshot_at(frame_ts or time.time())
                    self.telemetry_update.emit(snap)
                    # Always send frame to live preview
                    self.camera_frame.emit(frame)
                    if _is_invalid_video_frame(frame):
                        self.status_message.emit("Skipping blank/gray RTSP frame")
                        self.msleep(50)
                        continue
                    sig = _frame_signature(frame)
                    sig_diff = _frame_signature_diff(_last_accepted_sig, sig)
                    img_motion_px = _frame_motion_px(_last_accepted_sig, sig)
                    pose_move_m = _gps_distance_m(_last_accepted_snap, snap)
                    if sig_diff < 1.5 and pose_move_m > 1.0:
                        self.status_message.emit(
                            f"Skipping frozen video frame ({pose_move_m:.1f} m telemetry move)"
                        )
                        self.msleep(50)
                        continue
                    if img_motion_px < 1.0 and pose_move_m > 1.0:
                        self.status_message.emit(
                            f"Skipping buffered video frame ({pose_move_m:.1f} m telemetry move)"
                        )
                        self.msleep(50)
                        continue
                    if img_motion_px > 2.0 and pose_move_m < 0.25:
                        self.status_message.emit(
                            f"Skipping stale telemetry frame ({img_motion_px:.1f} px image move)"
                        )
                        self.msleep(50)
                        continue
                    # Only process for mapping when GPS is locked
                    if telem.is_good_gps():
                        # Skip if drone is on the ground (neg / low altitude)
                        if not self.allow_low_altitude and snap.get("alt_rel", 0) < MIN_ALTITUDE:
                            self.msleep(50)
                            continue
                        # Skip if telemetry is stale (no MAVLink update in 5 s)
                        if telem.is_stale():
                            self.status_message.emit("⚠ Telemetry stale - skipping frame")
                            self.msleep(50)
                            continue
                        # Skip if GPS is frozen (identical position 3+ times)
                        cur_lat, cur_lon = snap["lat"], snap["lon"]
                        cur_alt = snap.get("alt_rel", 0)
                        if (cur_lat == _last_lat and cur_lon == _last_lon
                                and cur_alt == _last_alt):
                            _stale_count += 1
                            if _stale_count >= 3:
                                self.status_message.emit(
                                    f"⚠ GPS frozen ({_stale_count}×) - skipping"
                                )
                                self.msleep(50)
                                continue
                        else:
                            _stale_count = 0
                        _last_lat, _last_lon, _last_alt = cur_lat, cur_lon, cur_alt

                        try:
                            jpeg = frame_to_tagged_jpeg(
                                frame,
                                snap,
                                attitude_fallback=self.attitude_fallback,
                            )
                            frame_num += 1
                            _last_accepted_sig = sig
                            _last_accepted_snap = snap.copy()
                            self.frame_ready.emit(jpeg, f"mavlink_{frame_num:04d}")
                        except Exception as e:
                            self.status_message.emit(f"Frame error: {e}")
            self.msleep(self.interval_ms)

        if cam is not None:
            cam.release()
        raw_records = telem.drain_raw_messages()
        if raw_records:
            self.raw_mavlink_messages.emit(raw_records)
        telem.stop()
        self.connection_changed.emit(False)
        self.status_message.emit("Drone link disconnected")


# ══════════════════════════════════════════════════════════════════════
#  MAP CANVAS - High-performance zoomable/pannable map view
# ══════════════════════════════════════════════════════════════════════

class MapCanvas(QGraphicsView):
    """Zoomable, pannable map display with satellite underlay."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)

        # View settings
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f"background: {C_BG};")

        self._zoom = 0
        self._empty = True
        self._fit_requested = True

        # Overlay text
        self._overlay_text = "NO SIGNAL"

        # Map metadata for overlays
        self._map_resolution = 0.5  # m/px - updated from service
        self._frame_count_overlay = 0

    def update_map(self, bgr_image: np.ndarray):
        """Update the map from a BGR numpy array (from render_map)."""
        h, w = bgr_image.shape[:2]
        rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._empty = False
        if self._fit_requested:
            self.fit_map()
            self._fit_requested = False

    def fit_map(self):
        if not self._empty:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = 0

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(factor, factor)
            self._zoom += 1
        else:
            self.scale(1 / factor, 1 / factor)
            self._zoom -= 1

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.viewport().rect()

        if self._empty:
            # Draw "NO SIGNAL" overlay
            painter.fillRect(rect, QColor(C_BG))
            pen = QPen(QColor(C_BORDER))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            cx, cy = rect.center().x(), rect.center().y()
            painter.drawLine(cx - 40, cy, cx + 40, cy)
            painter.drawLine(cx, cy - 40, cx, cy + 40)
            painter.drawEllipse(QPointF(cx, cy), 30, 30)
            font = QFont("Consolas", 14, QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor(C_TEXT_DIM))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._overlay_text)
        else:
            # ── Scale bar (bottom-left) ──
            self._draw_scale_bar(painter, rect)
            # ── North arrow (top-right) ──
            self._draw_north_arrow(painter, rect)
            # ── Frame counter (top-left) ──
            if self._frame_count_overlay > 0:
                painter.setPen(QColor(255, 255, 255, 200))
                painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                painter.drawText(12, 22, f"Frames: {self._frame_count_overlay}")

        painter.end()

    def _draw_scale_bar(self, painter: QPainter, rect):
        """Draw a scale bar in the bottom-left with automatic unit scaling."""
        # Compute scene-to-viewport scale factor
        t = self.transform()
        px_per_scene_unit = t.m11()  # horizontal scale factor
        if px_per_scene_unit <= 0:
            return
        # One scene pixel = self._map_resolution metres
        m_per_screen_px = self._map_resolution / px_per_scene_unit

        # Pick a nice round scale-bar length
        target_bar_px = 120
        target_m = target_bar_px * m_per_screen_px
        # Round to nearest nice value
        nice_values = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
        bar_m = min(nice_values, key=lambda v: abs(v - target_m))
        bar_px = int(bar_m / m_per_screen_px) if m_per_screen_px > 0 else 0
        if bar_px < 20 or bar_px > rect.width() // 2:
            return

        label = f"{bar_m} m" if bar_m < 1000 else f"{bar_m / 1000:.0f} km"

        x0 = 16
        y0 = rect.height() - 24

        # Background
        painter.setBrush(QBrush(QColor(0, 0, 0, 140)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(x0 - 4, y0 - 18, bar_px + 8, 28, 4, 4)

        # Bar
        pen = QPen(QColor(255, 255, 255, 220))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawLine(x0, y0, x0 + bar_px, y0)
        painter.drawLine(x0, y0 - 4, x0, y0 + 4)           # left tick
        painter.drawLine(x0 + bar_px, y0 - 4, x0 + bar_px, y0 + 4)  # right tick

        # Label
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255, 220))
        painter.drawText(x0, y0 - 6, label)

    def _draw_north_arrow(self, painter: QPainter, rect):
        """Draw a small north arrow in the top-right corner."""
        cx = rect.width() - 30
        cy = 32
        size = 16

        # Background circle
        painter.setBrush(QBrush(QColor(0, 0, 0, 140)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), size + 6, size + 6)

        # Arrow pointing up (north)
        pen = QPen(QColor(255, 255, 255, 220))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(cx, cy - size, cx, cy + size)
        # Arrowhead
        painter.drawLine(cx, cy - size, cx - 5, cy - size + 8)
        painter.drawLine(cx, cy - size, cx + 5, cy - size + 8)

        # "N" label
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QColor(255, 80, 80, 220))
        painter.drawText(cx - 4, cy - size - 4, "N")


# ══════════════════════════════════════════════════════════════════════
#  TELEMETRY HUD - Heads-up display panel
# ══════════════════════════════════════════════════════════════════════

class HudGauge(QFrame):
    """Single telemetry gauge - compact horizontal: LABEL  VALUE UNIT."""

    def __init__(self, label: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self._update_border(C_BORDER)

        # Flash timer - momentarily glows border on value change
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(lambda: self._update_border(C_BORDER))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self._label = QLabel(label.upper())
        self._label.setObjectName("hudLabel")
        self._label.setFixedWidth(80)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._value = QLabel("---")
        self._value.setObjectName("hudValue")
        self._prev_text = "---"
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._unit = QLabel(unit)
        self._unit.setObjectName("hudUnit")
        self._unit.setFixedWidth(28)
        self._unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._label)
        layout.addStretch()
        layout.addWidget(self._value)
        layout.addWidget(self._unit)

    def _update_border(self, color: str):
        self.setStyleSheet(f"""
            QFrame {{
                background: {C_PANEL};
                border: 1px solid {color};
                border-radius: 4px;
                padding: 2px;
            }}
        """)

    def set_value(self, text: str, color: str = None):
        changed = (text != self._prev_text)
        self._prev_text = text
        self._value.setText(text)
        c = color or C_TEXT_BRIGHT
        self._value.setStyleSheet(
            f"color: {c}; font-family: 'Consolas', monospace; "
            f"font-size: 15px; font-weight: bold;"
        )
        # Flash border green on value change
        if changed:
            self._update_border(color or C_ACCENT)
            self._flash_timer.start(400)


class TelemetryHUD(QWidget):
    """Compact telemetry heads-up display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(4, 4, 4, 4)

        self.altitude = HudGauge("Altitude", "m")
        self.speed = HudGauge("Speed", "m/s")
        self.heading = HudGauge("Heading", "°")
        self.satellites = HudGauge("Satellites", "")
        self.gps_fix = HudGauge("GPS Fix", "")
        self.hdop = HudGauge("HDOP", "")
        self.lat = HudGauge("Latitude", "")
        self.lon = HudGauge("Longitude", "")

        for g in [self.altitude, self.speed, self.heading,
                  self.satellites, self.gps_fix, self.hdop,
                  self.lat, self.lon]:
            layout.addWidget(g)

    def update_telemetry(self, snap: dict):
        alt = snap.get("alt_rel", 0)
        self.altitude.set_value(f"{alt:.1f}", C_GREEN if alt > 5 else C_YELLOW)

        vx, vy, vz = snap.get("vx", 0), snap.get("vy", 0), snap.get("vz", 0)
        spd = math.sqrt(vx*vx + vy*vy + vz*vz)
        self.speed.set_value(f"{spd:.1f}")

        yaw = snap.get("yaw", 0)
        self.heading.set_value(f"{yaw:.0f}")

        sats = snap.get("satellites", 0)
        fix = snap.get("gps_fix", 0)
        hdop = snap.get("hdop", 999)
        self.satellites.set_value(f"{sats}", C_GREEN if sats >= 10 else (C_YELLOW if sats >= 6 else C_RED))
        fix_names = {0: "No Fix", 1: "No Fix", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK Float", 6: "RTK Fix"}
        fix_color = C_GREEN if fix >= 3 else C_RED
        self.gps_fix.set_value(fix_names.get(fix, f"Type {fix}"), fix_color)
        self.hdop.set_value(f"{hdop:.1f}", C_GREEN if hdop < 2 else (C_YELLOW if hdop < 5 else C_RED))

        lat, lon = snap.get("lat", 0), snap.get("lon", 0)
        self.lat.set_value(f"{lat:.6f}")
        self.lon.set_value(f"{lon:.6f}")

    def set_from_mapper(self, service: MapperService):
        """Show mapper-derived info when no live telemetry (simulation / upload)."""
        pe = service.pose_extractor
        if pe.origin_lat is not None:
            self.lat.set_value(f"{pe.origin_lat:.6f}")
            self.lon.set_value(f"{pe.origin_lon:.6f}")

        n_frames = len(service.metrics_log)
        if service.metrics_log:
            last = service.metrics_log[-1]
            alt = last.get("altitude", 0)
            self.altitude.set_value(
                f"{alt:.1f}", C_GREEN if alt > 10 else C_YELLOW
            )
            # Speed from successive GPS positions
            if n_frames >= 2:
                prev = service.metrics_log[-2]
                dx = last.get("gps_x", 0) - prev.get("gps_x", 0)
                dy = last.get("gps_y", 0) - prev.get("gps_y", 0)
                dist = math.sqrt(dx * dx + dy * dy)
                self.speed.set_value(f"{dist:.1f}", C_TEXT_BRIGHT)
            # Heading from GPS track
            if n_frames >= 2:
                prev = service.metrics_log[-2]
                dx = last.get("gps_y", 0) - prev.get("gps_y", 0)
                dy = last.get("gps_x", 0) - prev.get("gps_x", 0)
                hdg = math.degrees(math.atan2(dx, dy)) % 360
                self.heading.set_value(f"{hdg:.0f}")

        # Dynamic labels for simulation mode
        tiles = len(service.mapper.tiles)
        self.satellites._label.setText("TILES")
        self.satellites.set_value(
            f"{tiles}", C_ACCENT if tiles > 0 else C_TEXT_DIM
        )

        self.gps_fix._label.setText("FRAMES")
        self.gps_fix.set_value(
            f"{n_frames}", C_GREEN if n_frames > 0 else C_TEXT_DIM
        )

        # Correction magnitude from pose graph
        if service.metrics_log and "correction_mag" in service.metrics_log[-1]:
            corr = service.metrics_log[-1]["correction_mag"]
            self.hdop._label.setText("CORRECTION")
            corr_color = C_GREEN if corr < 1 else (C_YELLOW if corr < 5 else C_RED)
            self.hdop.set_value(f"{corr:.2f}", corr_color)


# ══════════════════════════════════════════════════════════════════════
#  CAMERA PREVIEW - Live video feed panel
# ══════════════════════════════════════════════════════════════════════

class CameraPreview(QLabel):
    """Displays camera frames as a QLabel with aspect-ratio scaling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 150)
        self.setStyleSheet(f"background: {C_BG}; border: 1px solid {C_BORDER}; border-radius: 4px;")
        self.setText("CAMERA OFFLINE")
        self.setFont(QFont("Consolas", 10))
        self._has_frame = False

    def update_frame(self, bgr_frame: np.ndarray):
        h, w = bgr_frame.shape[:2]
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pixmap)
        self._has_frame = True


# ══════════════════════════════════════════════════════════════════════
#  PERFORMANCE PANEL
# ══════════════════════════════════════════════════════════════════════

class PerformancePanel(QWidget):
    """Real-time performance metrics with threshold indicators and dual timing bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._labels = {}
        self._dots = {}
        # (key, display_name, unit, good_thresh, warn_thresh)
        # For FPS: higher=better.  For ms / queue: lower=better.
        stats_info = [
            ("fps",        "Throughput",  "fps",   1.0,   0.3),
            ("process_ms", "Process",     "ms",    500,   1000),
            ("render_ms",  "Render",      "ms",    200,   500),
            ("tiles",      "Tiles",       "",      None,  None),
            ("memory",     "Memory",      "MB",    200,   500),
            ("frames",     "Frames",      "",      None,  None),
            ("gsd",        "GSD",         "m/px",  None,  None),
            ("coverage",   "Coverage",    "m\u00b2",    None,  None),
            ("queue",      "Queue",       "",      2,     5),
        ]
        self._thresholds = {}

        for key, name, unit, good, warn in stats_info:
            row = QHBoxLayout()
            row.setSpacing(4)
            dot = QLabel("\u25cf")
            dot.setFixedWidth(12)
            dot.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 8px;")
            lbl = QLabel(name)
            lbl.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 11px;")
            val = QLabel("---")
            val.setStyleSheet(
                f"color: {C_TEXT_BRIGHT}; font-weight: bold; "
                f"font-family: 'Consolas', monospace; font-size: 12px;"
            )
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            unit_lbl = QLabel(unit)
            unit_lbl.setStyleSheet(f"color: {C_ACCENT_DIM}; font-size: 10px;")
            unit_lbl.setFixedWidth(30)
            row.addWidget(dot)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            row.addWidget(unit_lbl)
            layout.addLayout(row)
            self._labels[key] = val
            self._dots[key] = dot
            if good is not None:
                self._thresholds[key] = (good, warn)

        # Dual timing bars
        layout.addSpacing(6)
        bar_title = QLabel("PIPELINE LOAD")
        bar_title.setStyleSheet(
            f"color: {C_TEXT_DIM}; font-size: 10px; font-weight: bold;"
        )
        layout.addWidget(bar_title)
        self._process_bar = self._make_bar("Process")
        self._render_bar = self._make_bar("Render")
        layout.addWidget(self._process_bar)
        layout.addWidget(self._render_bar)
        layout.addStretch()

    @staticmethod
    def _make_bar(label: str) -> QProgressBar:
        bar = QProgressBar()
        bar.setMaximum(1000)
        bar.setFormat(f"{label}: 0 ms")
        bar.setFixedHeight(16)
        bar.setStyleSheet(f"""
            QProgressBar {{
                background: {C_PANEL};
                border: 1px solid {C_BORDER};
                border-radius: 3px;
                text-align: center;
                color: {C_TEXT_DIM};
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {C_GREEN}, stop:0.5 {C_YELLOW}, stop:1 {C_RED});
                border-radius: 2px;
            }}
        """)
        return bar

    def update_stats(self, **kwargs):
        for key, val in kwargs.items():
            if key not in self._labels:
                continue
            text = f"{val:.1f}" if isinstance(val, float) else str(val)
            self._labels[key].setText(text)

            # Threshold-based dot colour
            if key in self._thresholds:
                good, warn = self._thresholds[key]
                try:
                    v = float(val)
                except (ValueError, TypeError):
                    v = 0
                if key == "fps":
                    dot_c = C_GREEN if v >= good else (C_YELLOW if v >= warn else C_RED)
                else:
                    dot_c = C_GREEN if v <= good else (C_YELLOW if v <= warn else C_RED)
                self._dots[key].setStyleSheet(f"color: {dot_c}; font-size: 8px;")

        # Timing bars
        proc = kwargs.get("process_ms", 0)
        rend = kwargs.get("render_ms", 0)
        if isinstance(proc, (int, float)):
            self._process_bar.setValue(min(int(proc), 1000))
            self._process_bar.setFormat(f"Process: {proc:.0f} ms")
        if isinstance(rend, (int, float)):
            self._render_bar.setValue(min(int(rend), 1000))
            self._render_bar.setFormat(f"Render: {rend:.0f} ms")


# ══════════════════════════════════════════════════════════════════════
#  COVERAGE PLOT
# ══════════════════════════════════════════════════════════════════════

class CoveragePlotWidget(QWidget):
    """Mini-map showing image footprints and flight path.

    Draws a top-down view of all projected image outlines (semi-transparent
    cyan polygons) and the flight path line, sized to fit inside the right
    dock panel.  Updated every ~1 s from ``MultiBandMap2D.get_coverage_data()``.
    """

    _PAD = 12  # pixels of padding inside the widget

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setMaximumHeight(260)
        self._flight_path: list[tuple[float, float]] = []
        self._footprints: list = []
        self._bounds: tuple | None = None
        self._area_m2: float = 0.0
        self._last_frame_count: int = 0

    # ── public update API ──

    def set_data(self, coverage_data: dict):
        """Accept dict from ``MultiBandMap2D.get_coverage_data()``."""
        self._flight_path = coverage_data.get("flight_path", [])
        self._footprints = coverage_data.get("footprints", [])
        self._bounds = coverage_data.get("bounds")
        self._area_m2 = coverage_data.get("area_m2", 0.0)
        self.update()  # schedule repaint

    # ── coordinate transform helpers ──

    def _metric_to_widget(self, mx: float, my: float,
                          xmin: float, ymin: float,
                          scale: float) -> QPointF:
        """Map metric coords to widget pixel coords."""
        px = self._PAD + (mx - xmin) * scale
        py = self._PAD + (my - ymin) * scale
        return QPointF(px, py)

    # ── painting ──

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor(C_PANEL))
        p.setPen(QPen(QColor(C_BORDER), 1))
        p.drawRect(0, 0, w - 1, h - 1)

        if not self._bounds or not self._footprints:
            p.setPen(QColor(C_TEXT_DIM))
            p.setFont(QFont("Consolas", 10))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "No coverage data yet")
            p.end()
            return

        xmin, xmax, ymin, ymax = self._bounds
        span_x = xmax - xmin
        span_y = ymax - ymin
        if span_x < 0.1 or span_y < 0.1:
            p.end()
            return

        draw_w = w - 2 * self._PAD
        draw_h = h - 2 * self._PAD - 20  # reserve 20 px for text at bottom
        if draw_w < 10 or draw_h < 10:
            p.end()
            return

        scale = min(draw_w / span_x, draw_h / span_y)

        # Centre the drawing
        used_w = span_x * scale
        used_h = span_y * scale
        x_off = (draw_w - used_w) / 2
        y_off = (draw_h - used_h) / 2

        def to_pt(mx, my):
            px = self._PAD + x_off + (mx - xmin) * scale
            py = self._PAD + y_off + (my - ymin) * scale
            return QPointF(px, py)

        # Draw footprints as semi-transparent polygons
        from PyQt6.QtGui import QPolygonF
        fill_color = QColor(C_ACCENT)
        fill_color.setAlpha(35)
        outline_color = QColor(C_ACCENT)
        outline_color.setAlpha(90)
        p.setPen(QPen(outline_color, 1))
        p.setBrush(QBrush(fill_color))
        for fp in self._footprints:
            poly = QPolygonF()
            for pt in fp:
                poly.append(to_pt(float(pt[0]), float(pt[1])))
            poly.append(to_pt(float(fp[0][0]), float(fp[0][1])))  # close
            p.drawPolygon(poly)

        # Draw flight path line
        if len(self._flight_path) >= 2:
            path_pen = QPen(QColor(C_YELLOW), 2)
            p.setPen(path_pen)
            for i in range(1, len(self._flight_path)):
                p1 = to_pt(*self._flight_path[i - 1])
                p2 = to_pt(*self._flight_path[i])
                p.drawLine(p1, p2)

            # Start marker (green dot)
            sp = to_pt(*self._flight_path[0])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C_GREEN))
            p.drawEllipse(sp, 4, 4)

            # End marker (red dot)
            ep = to_pt(*self._flight_path[-1])
            p.setBrush(QColor(C_RED))
            p.drawEllipse(ep, 4, 4)

        # Coverage area text
        area = self._area_m2
        if area > 1_000_000:
            area_str = f"{area / 1_000_000:.2f} km\u00b2"
        elif area > 10_000:
            area_str = f"{area / 10_000:.2f} ha"
        else:
            area_str = f"{area:.0f} m\u00b2"
        dims_str = f"{span_x:.0f}\u00d7{span_y:.0f} m"

        p.setPen(QColor(C_TEXT_BRIGHT))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        text_y = h - 6
        p.drawText(self._PAD, text_y, f"Area: {area_str}")
        p.setPen(QColor(C_TEXT_DIM))
        p.drawText(w - self._PAD - p.fontMetrics().horizontalAdvance(dims_str),
                   text_y, dims_str)

        p.end()


# ══════════════════════════════════════════════════════════════════════
#  LOG CONSOLE
# ══════════════════════════════════════════════════════════════════════

class LogConsole(QTextEdit):
    """Scrolling log console."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(150)

    def log(self, msg: str, level: str = "info"):
        colors = {"info": C_TEXT_DIM, "success": C_GREEN, "warn": C_YELLOW, "error": C_RED}
        color = colors.get(level, C_TEXT_DIM)
        ts = datetime.now().strftime("%H:%M:%S")
        self.append(f'<span style="color:{C_TEXT_DIM}">[{ts}]</span> '
                     f'<span style="color:{color}">{msg}</span>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ══════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════

class GCSMainWindow(QMainWindow):
    """SkyForge - Ground Control Station Main Window."""

    def __init__(self, args=None):
        super().__init__()
        self.setWindowTitle(f"SkyForge GCS v{__version__} - Aerial Mapping Station")
        self.setMinimumSize(1280, 800)
        self.resize(1600, 960)

        # Set window icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "skyforge.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # --- QSettings for persistence ---
        self._settings = QSettings("SkyForge", "GCS")

        # --- Service ---
        self._service = MapperService.get_instance()
        self._service.show_satellite = self._settings.value("map/satellite", True, type=bool)
        self._service.show_flight_path = self._settings.value("map/flightpath", True, type=bool)

        # --- Mission manager ---
        try:
            self._mission_manager = MissionManager()
        except Exception:
            self._mission_manager = None
        self._current_mission = None
        self._current_input_source = ""

        # --- Workers ---
        self._processor = MapProcessorWorker(self._service)
        self._processor.image_processed.connect(self._on_image_processed)
        self._processor.map_rendered.connect(self._on_map_rendered)
        self._processor.error_occurred.connect(self._on_error)
        self._processor.processing_time.connect(self._on_processing_time)
        self._processor.render_time.connect(self._on_render_time)
        self._processor.start()

        self._sim_worker = None
        self._mav_worker = None
        self._folder_queue_active = False

        # Performance tracking
        self._frame_count = 0
        self._frame_save_count = 0  # frames saved to mission folder
        self._telemetry_save_count = 0  # telemetry snapshots saved to mission folder
        self._raw_mavlink_save_count = 0  # raw MAVLink records saved to mission folder
        self._record_mavlink_inputs = False
        self._fps_timer = QElapsedTimer()
        self._fps_timer.start()
        self._fps_count = 0
        self._last_fps = 0.0
        self._last_process_ms = 0.0
        self._last_render_ms = 0.0

        # --- Build UI ---
        self._build_toolbar()
        self._build_central()
        self._build_right_dock()
        self._build_bottom_dock()
        self._build_status_bar()
        self._build_menu_bar()

        # --- Restore window state ---
        self._restore_settings()

        # --- Refresh timer ---
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._tick)
        self._refresh_timer.start(100)  # 10 Hz UI refresh

        # Auto-start
        if args and args.simulate:
            QTimer.singleShot(500, self._start_simulation)
        if args and args.mavlink:
            QTimer.singleShot(500, self._start_mavlink)

    # ─────────────── Build UI ───────────────

    def _build_toolbar(self):
        tb = QToolBar("Main Toolbar")
        tb.setObjectName("mainToolbar")
        tb.setIconSize(QSize(20, 20))
        tb.setMovable(False)
        self.addToolBar(tb)

        # Logo/title
        title = QLabel("  SKYFORGE - GCS  ")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {C_ACCENT}; letter-spacing: 3px;")
        tb.addWidget(title)
        tb.addSeparator()

        # Connection mode
        tb.addWidget(QLabel("  Mode: "))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Folder", "Live", "File"])
        self._mode_combo.setFixedWidth(110)
        self._mode_combo.setToolTip(
            "Select operation mode:\n"
            "  Folder - replay a saved mission folder\n"
            "  Live - connect to the drone\n"
            "  File - load selected images"
        )
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        tb.addWidget(self._mode_combo)

        # Start/Stop
        self._start_btn = QPushButton("▶  START")
        self._start_btn.setObjectName("accentBtn")
        self._start_btn.setFixedWidth(110)
        self._start_btn.setToolTip("Start or stop the current mapping operation (Shortcut: Space)")
        self._start_btn.clicked.connect(self._on_start_stop)
        tb.addWidget(self._start_btn)

        tb.addSeparator()

        # Map controls
        self._satellite_cb = QCheckBox("Satellite")
        self._satellite_cb.setChecked(self._service.show_satellite)
        self._satellite_cb.setToolTip(
            "Enable satellite imagery background (requires internet).\n"
            "Disable for offline / field use to skip tile downloads."
        )
        self._satellite_cb.toggled.connect(self._toggle_satellite)
        tb.addWidget(self._satellite_cb)

        self._flightpath_cb = QCheckBox("Flight Path")
        self._flightpath_cb.setChecked(self._service.show_flight_path)
        self._flightpath_cb.setToolTip("Show the drone’s flight path overlay on the map")
        self._flightpath_cb.toggled.connect(lambda v: setattr(self._service, 'show_flight_path', v))
        tb.addWidget(self._flightpath_cb)

        tb.addSeparator()

        # Processing mode
        tb.addWidget(QLabel("  Processing: "))
        self._pipeline_combo = QComboBox()
        self._pipeline_combo.addItems(["Quick Map", "High Accuracy (slower)"])
        self._pipeline_combo.setFixedWidth(170)
        self._pipeline_combo.setToolTip(
            "Quick Map - Fast processing using GPS data only\n"
            "High Accuracy - Pose graph optimization for"
            " better alignment (uses more CPU)"
        )
        self._pipeline_combo.currentIndexChanged.connect(self._on_pipeline_changed)
        tb.addWidget(self._pipeline_combo)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # Reset
        self._reset_btn = QPushButton("⟲  RESET")
        self._reset_btn.setObjectName("dangerBtn")
        self._reset_btn.setFixedWidth(100)
        self._reset_btn.setToolTip("Clear the current map and all data (Ctrl+R)")
        self._reset_btn.clicked.connect(self._on_reset)
        tb.addWidget(self._reset_btn)

        # Export map image
        self._export_btn = QPushButton("💾  EXPORT IMAGE")
        self._export_btn.setFixedWidth(155)
        self._export_btn.setToolTip("Export the orthomosaic map as an image file")
        self._export_btn.clicked.connect(self._on_export_map)
        tb.addWidget(self._export_btn)

        # Save mission record
        self._export_mission_btn = QPushButton("📦  SAVE MISSION")
        self._export_mission_btn.setFixedWidth(135)
        self._export_mission_btn.setToolTip("Save the full mission record with map, metadata, logs, and report")
        self._export_mission_btn.clicked.connect(self._on_export_mission)
        tb.addWidget(self._export_mission_btn)

        # Fit view
        self._fit_btn = QPushButton("◻  FIT")
        self._fit_btn.setFixedWidth(70)
        self._fit_btn.setToolTip("Fit the entire map in the view (F)")
        self._fit_btn.clicked.connect(lambda: self._map_canvas.fit_map())
        tb.addWidget(self._fit_btn)

    def _build_central(self):
        """Map canvas fills the center."""
        self._map_canvas = MapCanvas()
        self.setCentralWidget(self._map_canvas)

    def _build_right_dock(self):
        """Right dock: Telemetry HUD + Camera Preview + Settings."""
        dock = QDockWidget("MISSION CONTROL", self)
        dock.setObjectName("missionControlDock")
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setMinimumWidth(280)

        from PyQt6.QtWidgets import QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # --- Telemetry HUD ---
        self._hud = TelemetryHUD()
        hud_group = QGroupBox("TELEMETRY")
        hud_layout = QVBoxLayout(hud_group)
        hud_layout.setContentsMargins(2, 2, 2, 2)
        hud_layout.addWidget(self._hud)
        layout.addWidget(hud_group)

        # --- Camera Preview ---
        self._camera_preview = CameraPreview()
        self._camera_preview.setFixedHeight(140)
        cam_group = QGroupBox("CAMERA FEED")
        cam_layout = QVBoxLayout(cam_group)
        cam_layout.setContentsMargins(2, 2, 2, 2)
        cam_layout.addWidget(self._camera_preview)
        layout.addWidget(cam_group)

        # --- Map Settings ---
        settings_group = QGroupBox("MAP SETTINGS")
        sg_layout = QGridLayout(settings_group)
        sg_layout.setSpacing(6)

        sg_layout.addWidget(QLabel("Camera Profile"), 0, 0)
        self._camera_profile_combo = QComboBox()
        self._camera_profile_combo.addItems(list(CAMERA_PROFILES.keys()))
        self._camera_profile_combo.setToolTip("Select your drone’s camera model for accurate mapping")
        self._camera_profile_combo.currentTextChanged.connect(self._on_camera_profile_changed)
        sg_layout.addWidget(self._camera_profile_combo, 0, 1)

        self._custom_camera_widgets = []

        custom_focal_label = QLabel("Focal Length (mm)")
        self._custom_focal_spin = QDoubleSpinBox()
        self._custom_focal_spin.setRange(1.0, 200.0)
        self._custom_focal_spin.setDecimals(2)
        self._custom_focal_spin.setSingleStep(0.5)
        self._custom_focal_spin.setValue(24.0)
        sg_layout.addWidget(custom_focal_label, 1, 0)
        sg_layout.addWidget(self._custom_focal_spin, 1, 1)
        self._custom_camera_widgets.extend([custom_focal_label, self._custom_focal_spin])

        custom_sensor_label = QLabel("Sensor Width (mm)")
        self._custom_sensor_spin = QDoubleSpinBox()
        self._custom_sensor_spin.setRange(1.0, 100.0)
        self._custom_sensor_spin.setDecimals(2)
        self._custom_sensor_spin.setSingleStep(0.5)
        self._custom_sensor_spin.setValue(36.0)
        sg_layout.addWidget(custom_sensor_label, 2, 0)
        sg_layout.addWidget(self._custom_sensor_spin, 2, 1)
        self._custom_camera_widgets.extend([custom_sensor_label, self._custom_sensor_spin])

        custom_width_label = QLabel("Frame Width (px)")
        self._custom_width_spin = QSpinBox()
        self._custom_width_spin.setRange(160, 12000)
        self._custom_width_spin.setSingleStep(10)
        self._custom_width_spin.setValue(1280)
        sg_layout.addWidget(custom_width_label, 3, 0)
        sg_layout.addWidget(self._custom_width_spin, 3, 1)
        self._custom_camera_widgets.extend([custom_width_label, self._custom_width_spin])

        custom_height_label = QLabel("Frame Height (px)")
        self._custom_height_spin = QSpinBox()
        self._custom_height_spin.setRange(120, 12000)
        self._custom_height_spin.setSingleStep(10)
        self._custom_height_spin.setValue(720)
        sg_layout.addWidget(custom_height_label, 4, 0)
        sg_layout.addWidget(self._custom_height_spin, 4, 1)
        self._custom_camera_widgets.extend([custom_height_label, self._custom_height_spin])

        self._custom_focal_spin.valueChanged.connect(self._apply_custom_camera_profile)
        self._custom_sensor_spin.valueChanged.connect(self._apply_custom_camera_profile)
        self._custom_width_spin.valueChanged.connect(self._apply_custom_camera_profile)
        self._custom_height_spin.valueChanged.connect(self._apply_custom_camera_profile)
        self._on_camera_profile_changed(self._camera_profile_combo.currentText())

        sg_layout.addWidget(QLabel("Resolution (m/px)"), 5, 0)
        self._res_spin = QDoubleSpinBox()
        self._res_spin.setRange(0.1, 5.0)
        self._res_spin.setSingleStep(0.1)
        self._res_spin.setValue(self._service.map_resolution)
        self._res_spin.setToolTip("Map output resolution in metres per pixel\nLower = sharper but more memory")
        sg_layout.addWidget(self._res_spin, 5, 1)

        sg_layout.addWidget(QLabel("Satellite Area (m)"), 6, 0)
        self._sat_area_spin = QSpinBox()
        self._sat_area_spin.setRange(200, 3000)
        self._sat_area_spin.setSingleStep(100)
        self._sat_area_spin.setValue(self._service.satellite_area)
        self._sat_area_spin.setToolTip("Initial satellite imagery coverage area in metres")
        self._sat_area_spin.valueChanged.connect(lambda v: setattr(self._service, 'satellite_area', v))
        sg_layout.addWidget(self._sat_area_spin, 6, 1)

        sg_layout.addWidget(QLabel("Playback Delay (ms)"), 7, 0)
        self._sim_speed_spin = QSpinBox()
        self._sim_speed_spin.setRange(50, 5000)
        self._sim_speed_spin.setSingleStep(50)
        self._sim_speed_spin.setValue(300)
        self._sim_speed_spin.setToolTip("Delay between images in folder replay mode (ms)")
        sg_layout.addWidget(self._sim_speed_spin, 7, 1)

        layout.addWidget(settings_group)

        # --- MAVLink / Camera Settings ---
        mav_group = QGroupBox("DRONE & CAMERA")
        mg_layout = QGridLayout(mav_group)
        mg_layout.setSpacing(6)

        mg_layout.addWidget(QLabel("Drone Link"), 0, 0)
        from PyQt6.QtWidgets import QLineEdit
        self._mav_endpoint_input = QLineEdit()
        self._mav_endpoint_input.setPlaceholderText("auto  (e.g. udp:0.0.0.0:14550)")
        self._mav_endpoint_input.setToolTip(
            "Leave empty for auto-detect.\n"
            "Examples:\n"
            "  udp:0.0.0.0:14550\n"
            "  tcp:192.168.1.10:5760\n"
            "  /dev/ttyUSB0  or  COM3"
        )
        mg_layout.addWidget(self._mav_endpoint_input, 0, 1)

        mg_layout.addWidget(QLabel("Camera Source"), 1, 0)
        self._cam_source_input = QComboBox()
        self._cam_source_input.setEditable(True)
        self._cam_source_input.addItem("No Camera", "none")
        self._cam_source_input.addItem("Laptop Webcam", "0")
        self._cam_source_input.addItem("USB/HDMI Capture 1", "1")
        self._cam_source_input.addItem("USB/HDMI Capture 2", "2")
        self._cam_source_input.addItem("Skydroid C12 Live Feed (stream=1)", "rtsp://192.168.144.108:554/stream=1")
        self._cam_source_input.addItem("Enter URL", "")
        self._cam_source_input.setCurrentText("Skydroid C12 Live Feed (stream=1)")
        self._cam_source_input.setToolTip(
            "Camera source for live video feed:\n"
            "  Skydroid C12 Live Feed - RTSP stream=1\n"
            "  Laptop Webcam - device index 0\n"
            "  USB/HDMI Capture 1 - device index 1\n"
            "  USB/HDMI Capture 2 - device index 2\n"
            "  Enter URL - type a custom RTSP/UDP/TCP source"
        )
        mg_layout.addWidget(self._cam_source_input, 1, 1)

        mg_layout.addWidget(QLabel("Video Backend"), 2, 0)
        self._video_backend_combo = QComboBox()
        self._video_backend_combo.addItems([
            "Auto",
            "GStreamer Stable",
            "GStreamer Low Latency",
            "OpenCV/FFmpeg",
        ])
        self._video_backend_combo.setCurrentText("GStreamer Stable")
        self._video_backend_combo.setToolTip(
            "Auto tries GStreamer first when available, then OpenCV/FFmpeg.\n"
            "GStreamer Stable buffers more to avoid HEVC corruption during motion.\n"
            "Low Latency is faster but may break up on weak links."
        )
        mg_layout.addWidget(self._video_backend_combo, 2, 1)

        mg_layout.addWidget(QLabel("Capture Interval (ms)"), 3, 0)
        self._mav_interval_spin = QSpinBox()
        self._mav_interval_spin.setRange(500, 10000)
        self._mav_interval_spin.setSingleStep(250)
        self._mav_interval_spin.setValue(1000)
        self._mav_interval_spin.setToolTip("How often to capture a frame for mapping (ms)")
        mg_layout.addWidget(self._mav_interval_spin, 3, 1)

        mg_layout.addWidget(QLabel("Video Delay (ms)"), 4, 0)
        self._video_delay_spin = QSpinBox()
        self._video_delay_spin.setRange(0, 10000)
        self._video_delay_spin.setSingleStep(250)
        self._video_delay_spin.setValue(1000)
        self._video_delay_spin.setToolTip(
            "Compensates RTSP latency by tagging frames with older telemetry.\n"
            "Increase if the map appears ahead of the video."
        )
        mg_layout.addWidget(self._video_delay_spin, 4, 1)

        mg_layout.addWidget(QLabel("Attitude Fallback"), 5, 0)
        self._attitude_fallback_combo = QComboBox()
        self._attitude_fallback_combo.addItems([
            "Assume Stabilized Nadir",
            "Use Aircraft Attitude",
        ])
        self._attitude_fallback_combo.setCurrentText("Assume Stabilized Nadir")
        self._attitude_fallback_combo.setToolTip(
            "Used only when real gimbal telemetry is missing.\n"
            "Use Aircraft Attitude compensates aircraft roll/pitch during sideways flight.\n"
            "Assume Stabilized Nadir keeps roll 0 and pitch -90."
        )
        mg_layout.addWidget(self._attitude_fallback_combo, 5, 1)

        self._allow_low_alt_cb = QCheckBox("Allow ground test frames")
        self._allow_low_alt_cb.setToolTip(
            "Temporarily process MAVLink camera frames even when RelativeAltitude is below 2 m.\n"
            "Use only for bench testing; leave off for real missions."
        )
        mg_layout.addWidget(self._allow_low_alt_cb, 6, 0, 1, 2)

        layout.addWidget(mav_group)

        # --- Appearance & Preferences ---
        app_group = QGroupBox("APPEARANCE")
        ag_layout = QGridLayout(app_group)
        ag_layout.setSpacing(6)

        # Theme toggle
        ag_layout.addWidget(QLabel("Theme"), 0, 0)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["Dark", "Light"])
        self._theme_combo.setCurrentText("Dark")
        self._theme_combo.setToolTip("Switch between dark and light UI themes")
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        ag_layout.addWidget(self._theme_combo, 0, 1)

        # MAVLink endpoint preference
        ag_layout.addWidget(QLabel("Drone Link Default Port"), 1, 0)
        self._port_pref_combo = QComboBox()
        self._port_pref_combo.addItems(["Auto (14551 first)", "Safe (14551 only)", "QGC Compatible (14550)"])
        self._port_pref_combo.setCurrentText("QGC Compatible (14550)")
        self._port_pref_combo.setToolTip(
            "Choose which MAVLink port to prefer:\n"
            "  Auto (14551 first) - try 14551 before falling back to others\n"
            "  Safe (14551 only) - only use 14551 (won't conflict with QGC)\n"
            "  QGC Compatible (14550) - use 14550 as primary (legacy, may conflict)"
        )
        ag_layout.addWidget(self._port_pref_combo, 1, 1)

        layout.addWidget(app_group)

        # --- Performance ---
        self._perf_panel = PerformancePanel()
        perf_group = QGroupBox("PERFORMANCE")
        perf_layout = QVBoxLayout(perf_group)
        perf_layout.setContentsMargins(2, 2, 2, 2)
        perf_layout.addWidget(self._perf_panel)
        layout.addWidget(perf_group)

        # --- Coverage Plot ---
        self._coverage_plot = CoveragePlotWidget()
        cov_group = QGroupBox("AREA COVERAGE")
        cov_group.setToolTip(
            "Top-down view of mapped area.\n"
            "Cyan polygons = image footprints\n"
            "Yellow line = flight path\n"
            "Green dot = start, Red dot = current position"
        )
        cov_layout = QVBoxLayout(cov_group)
        cov_layout.setContentsMargins(2, 2, 2, 2)
        cov_layout.addWidget(self._coverage_plot)
        layout.addWidget(cov_group)

        layout.addStretch()
        scroll_area.setWidget(container)
        dock.setWidget(scroll_area)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _build_bottom_dock(self):
        """Bottom dock: Log console + progress bar."""
        dock = QDockWidget("LOG", self)
        dock.setObjectName("logDock")
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        # Progress
        prog_row = QHBoxLayout()
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(16)
        self._progress_label = QLabel("IDLE")
        self._progress_label.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 11px; min-width: 100px;")
        prog_row.addWidget(self._progress_label)
        prog_row.addWidget(self._progress_bar)
        layout.addLayout(prog_row)

        # Log
        self._log = LogConsole()
        layout.addWidget(self._log)

        dock.setWidget(container)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def _build_status_bar(self):
        sb = self.statusBar()
        self._status_conn = QLabel("⬤ DISCONNECTED")
        self._status_conn.setStyleSheet(f"color: {C_RED}; font-weight: bold; padding: 0 12px;")
        sb.addWidget(self._status_conn)

        self._status_mode = QLabel("Mode: Folder")
        sb.addWidget(self._status_mode)

        self._status_fps = QLabel("FPS: --")
        self._status_fps.setStyleSheet(f"color: {C_ACCENT}; font-weight: bold;")
        sb.addPermanentWidget(self._status_fps)

        self._status_time = QLabel("")
        sb.addPermanentWidget(self._status_time)

    def _build_menu_bar(self):
        mb = self.menuBar()

        # File menu
        file_menu = mb.addMenu("&File")
        export_action = QAction("Export Image...", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._on_export_map)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        open_logs_action = QAction("Open Log Folder", self)
        open_logs_action.triggered.connect(self._open_log_folder)
        file_menu.addAction(open_logs_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Tools menu
        tools_menu = mb.addMenu("&Tools")
        tiles_action = QAction("Download Offline Tiles...", self)
        tiles_action.setToolTip("Pre-download satellite tiles for offline field use")
        tiles_action.triggered.connect(self._show_tile_downloader)
        tools_menu.addAction(tiles_action)

        # Help menu
        help_menu = mb.addMenu("&Help")
        update_action = QAction("Check for Updates...", self)
        update_action.triggered.connect(self._check_for_updates)
        help_menu.addAction(update_action)
        update_source_action = QAction("Set Update Source...", self)
        update_source_action.triggered.connect(self._configure_update_source)
        help_menu.addAction(update_source_action)
        help_menu.addSeparator()
        shortcuts_action = QAction("Keyboard Shortcuts", self)
        shortcuts_action.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcuts_action)
        help_menu.addSeparator()
        about_action = QAction("About SkyForge", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _open_log_folder(self):
        """Open the log folder in the system file explorer."""
        import subprocess
        os.makedirs(SKYFORGE_LOG_DIR, exist_ok=True)
        subprocess.Popen(["explorer", SKYFORGE_LOG_DIR])

    def _show_tile_downloader(self):
        """Show the offline tile download dialog."""
        try:
            from tile_downloader import TileDownloadDialog
        except ModuleNotFoundError:
            QMessageBox.information(
                self,
                "Offline Tiles",
                "Offline tile download is not included in this build."
            )
            return
        dlg = TileDownloadDialog(self)
        # Pre-fill with current map center if available
        pe = self._service.pose_extractor
        if pe.origin_lat is not None:
            dlg._lat_input.setValue(pe.origin_lat)
            dlg._lon_input.setValue(pe.origin_lon)
        dlg.exec()

    def _configure_update_source(self):
        current = self._settings.value("updates/manifest_url", "", type=str)
        text, ok = QInputDialog.getText(
            self,
            "Update Source",
            "Enter update manifest URL or file path:",
            QLineEdit.EchoMode.Normal,
            current,
        )
        if not ok:
            return
        text = text.strip()
        self._settings.setValue("updates/manifest_url", text)
        if text:
            self._log.log(f"Update source set: {text}", "info")
        else:
            self._log.log("Update source cleared", "warn")

    def _check_for_updates(self):
        source = self._settings.value("updates/manifest_url", "", type=str).strip()
        if not source:
            self._configure_update_source()
            source = self._settings.value("updates/manifest_url", "", type=str).strip()
            if not source:
                return

        try:
            from updater import load_manifest, is_newer_version
            info = load_manifest(source)
        except Exception as e:
            QMessageBox.warning(self, "Update Check Failed", str(e))
            self._log.log(f"Update check failed: {e}", "error")
            return

        if not is_newer_version(info.latest_version, __version__):
            QMessageBox.information(
                self,
                "SkyForge GCS Updates",
                f"SkyForge GCS is up to date.\n\nCurrent version: {__version__}"
            )
            return

        notes = f"\n\nNotes:\n{info.notes}" if info.notes else ""
        reply = QMessageBox.question(
            self,
            "Update Available",
            f"Version {info.latest_version} is available.\n"
            f"Current version: {__version__}{notes}\n\n"
            "Download and install this update now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._download_and_launch_update(info)

    def _download_and_launch_update(self, info):
        try:
            from updater import download_update, launch_update_package
        except Exception as e:
            QMessageBox.warning(self, "Updater Missing", str(e))
            return

        update_dir = Path(SKYFORGE_DATA_DIR) / "updates"
        progress = QProgressDialog("Downloading update...", "Cancel", 0, 100, self)
        progress.setWindowTitle("SkyForge GCS Update")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def on_progress(done, total):
            if total:
                progress.setValue(min(100, int(done * 100 / total)))
            else:
                progress.setLabelText(f"Downloading update... {done / (1024 * 1024):.1f} MB")
            QApplication.processEvents()
            if progress.wasCanceled():
                raise RuntimeError("Update download cancelled.")

        try:
            package = download_update(info, update_dir, progress=on_progress)
            progress.setValue(100)
        except Exception as e:
            progress.close()
            QMessageBox.warning(self, "Update Download Failed", str(e))
            self._log.log(f"Update download failed: {e}", "error")
            return

        reply = QMessageBox.question(
            self,
            "Install Update",
            "The update was downloaded and verified.\n\n"
            "SkyForge GCS will close and apply the update now.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        if reply != QMessageBox.StandardButton.Ok:
            self._log.log(f"Update downloaded but not installed: {package}", "warn")
            return

        try:
            if info.install_mode == "replace_exe" and not getattr(sys, "frozen", False):
                raise RuntimeError(
                    "This update package replaces the packaged SkyForge_GCS.exe. "
                    "Run the packaged app to apply it."
                )
            launch_update_package(
                package,
                args=info.installer_args,
                install_mode=info.install_mode,
                current_exe=sys.executable,
            )
            self._log.log(f"Launching update package: {package}", "info")
            self.close()
        except Exception as e:
            QMessageBox.warning(self, "Install Update Failed", str(e))
            self._log.log(f"Update launch failed: {e}", "error")

    def _show_shortcuts(self):
        QMessageBox.information(
            self, "Keyboard Shortcuts",
            "<h3>SkyForge GCS Shortcuts</h3>"
            "<table>"
            "<tr><td><b>Space</b></td><td>Start / Stop</td></tr>"
            "<tr><td><b>F</b></td><td>Fit map to view</td></tr>"
            "<tr><td><b>Ctrl+R</b></td><td>Reset map</td></tr>"
            "<tr><td><b>Ctrl+E</b></td><td>Export image</td></tr>"
            "<tr><td><b>Ctrl+Q</b></td><td>Quit</td></tr>"
            "<tr><td><b>F11</b></td><td>Toggle fullscreen</td></tr>"
            "</table>"
        )

    def _show_about(self):
        QMessageBox.about(
            self,
            "About SkyForge GCS",
            f"<h2>SkyForge GCS</h2>"
            f"<p>Version {__version__}</p>"
            f"<p>Real-time aerial orthomosaic mapping with<br>"
            f"satellite underlay, MAVLink telemetry, and<br>"
            f"live camera feed.</p>"
            f"<p><small>Built by Jugal Alan - IIT Ropar</small></p>"
            f"<p><small>Contact: alanjugal@gmail.com</small></p>"
        )

    # ─────────────── Actions ───────────────

    def _on_mode_changed(self, mode: str):
        if hasattr(self, '_status_mode'):
            self._status_mode.setText(f"Mode: {mode}")

    def _on_start_stop(self):
        mode = self._mode_combo.currentText()
        if self._sim_worker or self._mav_worker or self._folder_queue_active:
            self._stop_current()
            return

        if mode == "Folder":
            self._start_simulation()
        elif mode == "Live":
            self._start_mavlink()
        elif mode == "File":
            self._start_file_upload()

    def _toggle_satellite(self, checked: bool):
        self._service.show_satellite = checked
        if hasattr(self, '_sat_area_spin'):
            self._sat_area_spin.setEnabled(checked)

    def _prepare_new_mapping_run(self):
        """Apply UI map settings and clear stale map state before a new run."""
        res = self._res_spin.value()
        self._service.reset_map(resolution=res)
        self._map_canvas._empty = True
        self._map_canvas._fit_requested = True
        self._frame_count = 0
        self._log.log(f"Map initialized at {res:.2f} m/px", "info")

    def _start_simulation(self):
        default_folder = os.path.join(os.path.dirname(__file__), "images-true")
        from PyQt6.QtWidgets import QFileDialog
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Mission Folder",
            default_folder if os.path.isdir(default_folder) else os.path.dirname(__file__),
        )
        if not chosen:
            return  # user cancelled
        folder = chosen
        self._current_input_source = folder
        if not os.path.isdir(folder):
            self._log.log(f"Mission folder not found: {folder}", "error")
            return
        self._prepare_new_mapping_run()
        self._log.log(f"Starting folder replay from {folder}", "info")
        self._progress_label.setText("FOLDER")
        self._start_btn.setText("■  STOP")
        self._start_btn.setObjectName("dangerBtn")
        self._start_btn.setStyleSheet(self._start_btn.styleSheet())  # force re-style

        interval = self._sim_speed_spin.value()
        self._sim_worker = SimulationWorker(folder, interval)
        self._sim_worker.frame_ready.connect(self._on_frame_ready)
        self._sim_worker.progress.connect(self._on_sim_progress)
        self._sim_worker.finished_sim.connect(self._on_sim_finished)
        self._sim_worker.start()
        self._set_connected(True, "FOLDER")
        self._record_mavlink_inputs = False

        # Create mission folder for this folder replay
        if getattr(self, '_mission_manager', None):
            try:
                self._current_mission = self._mission_manager.create_mission(name="folder")
                self._frame_save_count = 0
                self._telemetry_save_count = 0
                self._raw_mavlink_save_count = 0
                self._log.log(f"Created mission folder: {self._current_mission}", "info")
            except Exception as e:
                self._log.log(f"Mission create failed: {e}", "error")

    def _start_mavlink(self):
        self._log.log("Connecting to drone...", "info")
        self._current_input_source = "live"
        self._prepare_new_mapping_run()
        self._progress_label.setText("CONNECTING")
        self._record_mavlink_inputs = True
        self._start_btn.setText("■  STOP")

        # Read MAVLink endpoint
        mav_ep = self._mav_endpoint_input.text().strip()
        
        # If endpoint is empty, use the port preference setting
        if not mav_ep:
            pref_ep = self._get_mavlink_endpoint_for_preference()
            if pref_ep:
                mav_ep = pref_ep
                self._log.log(f"Using port preference: {mav_ep}", "info")
            # else: empty string means auto-detect (full fallback list)

        # Read camera source ("none" disables camera)
        cam_src_raw = self._selected_camera_source_value()
        if cam_src_raw.lower() == "none" or cam_src_raw == "":
            cam_src = None  # disable camera
            if self._cam_source_input.currentText().strip() == "Enter URL":
                self._log.log("Enter a camera URL before starting live camera feed", "warn")
        elif cam_src_raw.isdigit():
            cam_src = int(cam_src_raw)
        else:
            cam_src = cam_src_raw  # RTSP URL or device path

        interval = self._mav_interval_spin.value()
        video_delay = self._video_delay_spin.value()
        backend_label = self._video_backend_combo.currentText().lower()
        if "low latency" in backend_label:
            video_backend = "gstreamer_low_latency"
        elif "gstreamer" in backend_label:
            video_backend = "gstreamer_stable"
        elif "ffmpeg" in backend_label:
            video_backend = "ffmpeg"
        else:
            video_backend = "auto"
        attitude_fallback = (
            "stabilized"
            if "stabilized" in self._attitude_fallback_combo.currentText().lower()
            else "aircraft"
        )

        # Create mission folder before the live worker starts so raw MAVLink is captured from the beginning.
        if getattr(self, '_mission_manager', None):
            try:
                self._current_mission = self._mission_manager.create_mission(name="live")
                self._frame_save_count = 0
                self._telemetry_save_count = 0
                self._raw_mavlink_save_count = 0
                self._log.log(f"Created mission folder: {self._current_mission}", "info")
            except Exception as e:
                self._log.log(f"Mission create failed: {e}", "error")

        self._mav_worker = MAVLinkWorker(
            connection_str=mav_ep,
            camera_source=cam_src,
            interval_ms=interval,
            allow_low_altitude=self._allow_low_alt_cb.isChecked(),
            video_delay_ms=video_delay,
            video_backend=video_backend,
            attitude_fallback=attitude_fallback,
        )
        self._mav_worker.frame_ready.connect(self._on_frame_ready)
        self._mav_worker.telemetry_update.connect(self._on_telemetry_update)
        self._mav_worker.raw_mavlink_messages.connect(self._on_raw_mavlink_messages)
        self._mav_worker.camera_frame.connect(self._camera_preview.update_frame)
        self._mav_worker.status_message.connect(lambda m: self._log.log(m, "info"))
        self._mav_worker.connection_changed.connect(lambda ok: self._set_connected(ok, "LIVE"))
        self._mav_worker.start()

    def _start_file_upload(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Image Files", "",
            "JPEG Images (*.jpg *.jpeg *.JPG *.JPEG);;All Files (*)"
        )
        if not files:
            return
        self._current_input_source = f"{len(files)} selected files"
        self._prepare_new_mapping_run()
        self._log.log(f"Loading {len(files)} images...", "info")
        self._progress_label.setText("LOADING")
        self._record_mavlink_inputs = False
        # Create mission folder for this file import
        if getattr(self, '_mission_manager', None):
            try:
                self._current_mission = self._mission_manager.create_mission(name="file")
                self._frame_save_count = 0
                self._telemetry_save_count = 0
                self._raw_mavlink_save_count = 0
                self._log.log(f"Created mission folder: {self._current_mission}", "info")
            except Exception as e:
                self._log.log(f"Mission create failed: {e}", "error")
        total = len(files)
        for i, fp in enumerate(sorted(files)):
            try:
                with open(fp, "rb") as f:
                    data = f.read()
                self._on_frame_ready(data, os.path.basename(fp))
            except Exception as e:
                self._log.log(f"Failed to read {fp}: {e}", "error")
            self._progress_bar.setValue(int((i + 1) / total * 100))
        self._progress_bar.setValue(100)
        self._progress_label.setText("QUEUED")
        self._log.log(f"Loaded {total} images for processing", "success")

    def _stop_current(self):
        if self._sim_worker:
            self._sim_worker.stop()
            self._sim_worker = None
        if self._mav_worker:
            self._mav_worker.stop()
            self._mav_worker = None
        if self._folder_queue_active and self._processor:
            dropped = self._processor.clear_queue()
            if dropped:
                self._log.log(f"Cleared {dropped} queued folder frames", "warn")
        self._folder_queue_active = False
        self._start_btn.setText("▶  START")
        self._start_btn.setObjectName("accentBtn")
        self._start_btn.setStyleSheet(self._start_btn.styleSheet())
        self._progress_label.setText("IDLE")
        self._set_connected(False)
        self._log.log("Stopped", "warn")

    def _on_reset(self):
        reply = QMessageBox.question(
            self, "Confirm Reset",
            "This will clear the current map and all collected data.\nAre you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._stop_current()
        res = self._res_spin.value()
        self._service.reset_map(resolution=res)
        self._map_canvas._empty = True
        self._map_canvas._fit_requested = True
        self._map_canvas.viewport().update()
        self._frame_count = 0
        self._log.log("Map reset", "warn")
        self._perf_panel.update_stats(fps=0, process_ms=0, render_ms=0,
                                      tiles=0, memory=0, frames=0, queue=0)

    def _on_export_map(self):
        """Export the current orthomosaic map to a PNG/JPEG file."""
        mapper = self._service.mapper
        if not mapper or not mapper.tiles:
            QMessageBox.information(self, "Export Image", "No map data to export.")
            return
        # Render full-quality map without flight path for clean export
        sat_bg = self._service._get_satellite_bg(mapper) if self._service.show_satellite else None
        img = mapper.render_map(0, show_flight_path=False, satellite_bg=sat_bg)
        if img is None:
            QMessageBox.warning(self, "Export Image", "Failed to render map.")
            return
        # Suggest filename with timestamp
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"skyforge_map_{ts}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Image", default_name,
            "PNG Image (*.png);;JPEG Image (*.jpg);;TIFF Image (*.tiff)"
        )
        if not path:
            return
        success = cv2.imwrite(path, img)
        if success:
            h, w = img.shape[:2]
            res = self._service.map_resolution
            self._log.log(f"Image exported: {w}x{h} px, {res} m/px -> {path}", "info")
            # Also save a copy into the mission folder if available
            if getattr(self, '_current_mission', None) and getattr(self, '_mission_manager', None):
                try:
                    fname = os.path.basename(path)
                    saved = self._mission_manager.export_image(self._current_mission, img, fname)
                    self._log.log(f"Saved export to mission folder: {saved}", "info")
                except Exception as e:
                    self._log.log(f"Failed to save export to mission folder: {e}", "error")
            QMessageBox.information(self, "Export Image", f"Image saved to:\n{path}\n\n{w}x{h} pixels, {res} m/px")
        else:
            QMessageBox.warning(self, "Export Image", "Failed to write file.")

    def _on_export_mission(self):
        """Save a complete mission record: map, metadata, logs, telemetry, and PDF report."""
        if not getattr(self, '_current_mission', None):
            QMessageBox.information(self, "Save Mission", "No active mission to save.")
            return

        mapper = self._service.mapper
        if not mapper or not mapper.tiles:
            QMessageBox.information(self, "Save Mission", "No map data yet.")
            return

        # Render map for export
        sat_bg = self._service._get_satellite_bg(mapper) if self._service.show_satellite else None
        img = mapper.render_map(0, show_flight_path=False, satellite_bg=sat_bg)
        if img is None:
            QMessageBox.warning(self, "Save Mission", "Failed to render map.")
            return

        try:
            mm = self._mission_manager
            mission_path = self._current_mission

            # 1. Save final ortho map as high-quality PNG
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            map_fname = f"ortho_{ts}.png"
            mm.export_image(mission_path, img, map_fname)
            self._log.log(f"Saved ortho map: {map_fname}", "info")

            # 2. Update mission metadata with summary
            perf_summary = self._service.get_performance_summary()
            metadata = {
                "name": "Mission",
                "start_time": datetime.now().isoformat(),
                "frames_processed": self._frame_count,
                "frames_saved": self._frame_save_count,
                "telemetry_snapshots_saved": self._telemetry_save_count,
                "raw_mavlink_records_saved": self._raw_mavlink_save_count,
                "input_source": self._current_input_source,
                "tiles_count": len(mapper.tiles),
                "map_resolution_m_px": self._service.map_resolution,
                "camera_profile": self._camera_profile_combo.currentText(),
                "camera_focal_len_mm": self._service.focal_len_mm,
                "camera_sensor_width_mm": self._service.sensor_width_mm,
                "camera_profile_width_px": self._service.img_width_px,
                "camera_profile_height_px": self._service.img_height_px,
                "attitude_fallback": self._attitude_fallback_combo.currentText(),
                "ortho_filename": map_fname,
            }
            if perf_summary:
                metadata.update({
                    "fps": perf_summary.get('fps', 0),
                    "avg_total_ms": perf_summary.get('avg_total_ms', 0),
                    "elapsed_sec": perf_summary.get('elapsed_sec', 0),
                    "tile_memory_mb": perf_summary.get('tile_memory_mb', 0),
                })
            mm.save_metadata(mission_path, metadata)
            self._log.log("Saved mission metadata", "info")

            # 3. Save processing summary as JSON
            summary_fname = "processing_summary.json"
            summary_data = {
                "mission_metadata": metadata,
                "performance_summary": perf_summary,
                "service_metrics": {
                    "enable_pose_graph": self._service.enable_pose_graph,
                    "comparison_mode": self._service.comparison_mode,
                    "show_satellite": self._service.show_satellite,
                },
            }
            with open(mission_path / summary_fname, "w", encoding="utf-8") as f:
                json.dump(summary_data, f, indent=2, default=str)
            self._log.log(f"Saved processing summary: {summary_fname}", "info")

            # 4. Attempt to generate PDF report (if matplotlib available)
            try:
                self._generate_mission_report_pdf(mission_path, metadata, perf_summary)
            except Exception as e:
                self._log.log(f"PDF report generation skipped: {e}", "warn")

            # 5. Show mission folder
            folder_str = str(mission_path)
            QMessageBox.information(
                self, "Mission Saved",
                f"Mission saved to:\n{folder_str}\n\n"
                f"Files:\n"
                f"  • {map_fname} (ortho map)\n"
                f"  • metadata.json (mission info)\n"
                f"  • {summary_fname} (perf stats)\n"
                f"  • mission_report.pdf (optional)\n"
                f"  • frame_*.jpg + telemetry.jsonl + mavlink_raw.jsonl (live drone only)"
            )
            self._log.log(f"Mission saved: {folder_str}", "success")

        except Exception as e:
            self._log.log(f"Save mission failed: {e}", "error")
            QMessageBox.warning(self, "Save Mission Failed", f"Error: {str(e)}")

    def _generate_mission_report_pdf(self, mission_path, metadata: dict, perf_summary):
        """Generate a PDF report for the mission (optional, requires matplotlib)."""
        try:
            import matplotlib
            matplotlib.use("Agg")  # non-GUI backend
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_pdf import PdfPages
        except ImportError:
            # PDF generation not available
            return

        try:
            pdf_path = mission_path / "mission_report.pdf"
            with PdfPages(str(pdf_path)) as pdf:
                # Page 1: Mission summary
                fig, ax = plt.subplots(figsize=(8.5, 11))
                ax.axis('off')

                title_y = 0.95
                ax.text(0.5, title_y, "SkyForge Mission Report", ha='center', va='top',
                        fontsize=18, fontweight='bold', transform=ax.transAxes)

                content_y = 0.88
                line_height = 0.04

                # Mission metadata
                ax.text(0.1, content_y, "Mission Information", fontsize=12, fontweight='bold',
                        transform=ax.transAxes)
                content_y -= line_height * 1.5

                info_lines = [
                    f"Start Time: {metadata.get('start_time', 'N/A')}",
                    f"Frames Processed: {metadata.get('frames_processed', 0)}",
                    f"Frames Saved: {metadata.get('frames_saved', 0)}",
                    f"Tiles Generated: {metadata.get('tiles_count', 0)}",
                    f"Map Resolution: {metadata.get('map_resolution_m_px', 0.5)} m/px",
                ]
                for line in info_lines:
                    ax.text(0.1, content_y, line, fontsize=10, transform=ax.transAxes)
                    content_y -= line_height

                # Performance summary
                content_y -= line_height
                ax.text(0.1, content_y, "Performance", fontsize=12, fontweight='bold',
                        transform=ax.transAxes)
                content_y -= line_height * 1.5

                if perf_summary:
                    perf_lines = [
                        f"Throughput: {perf_summary.get('fps', 0):.2f} fps",
                        f"Avg Frame Time: {perf_summary.get('avg_total_ms', 0):.1f} ms",
                        f"Elapsed Time: {perf_summary.get('elapsed_sec', 0):.1f} s",
                        f"Total Data: {perf_summary.get('total_images_mb', 0):.1f} MB",
                        f"Peak Memory: {perf_summary.get('tile_memory_mb', 0):.1f} MB",
                    ]
                    for line in perf_lines:
                        ax.text(0.1, content_y, line, fontsize=10, transform=ax.transAxes)
                        content_y -= line_height

                pdf.savefig(fig, bbox_inches='tight')
                plt.close(fig)

            self._log.log(f"Generated PDF report: {pdf_path.name}", "info")

        except Exception as e:
            logger.debug(f"PDF generation failed: {e}")
            raise

    def _on_pipeline_changed(self, idx):
        if idx == 0:
            self._service.enable_pose_graph = False
            self._service.comparison_mode = False
        elif idx == 1:
            self._service.enable_pose_graph = True
            self._service.comparison_mode = False
        self._log.log(f"Processing: {self._pipeline_combo.currentText()}", "info")

    def _on_camera_profile_changed(self, name: str):
        is_custom = name == "Custom"
        for widget in getattr(self, "_custom_camera_widgets", []):
            widget.setVisible(is_custom)
        if is_custom:
            self._apply_custom_camera_profile()
            return

        profile = CAMERA_PROFILES.get(name)
        if profile:
            focal, sensor_w, img_w, img_h = profile
            self._service.update_parameters(focal, sensor_w, img_w, img_h)
            if hasattr(self, "_log"):
                self._log.log(f"Camera: {name} ({focal}mm, {sensor_w}mm sensor, {img_w}x{img_h})", "info")

    def _apply_custom_camera_profile(self):
        if self._camera_profile_combo.currentText() != "Custom":
            return
        focal = float(self._custom_focal_spin.value())
        sensor_w = float(self._custom_sensor_spin.value())
        img_w = int(self._custom_width_spin.value())
        img_h = int(self._custom_height_spin.value())
        self._service.update_parameters(focal, sensor_w, img_w, img_h)
        if hasattr(self, "_log"):
            self._log.log(f"Camera: Custom ({focal}mm, {sensor_w}mm sensor, {img_w}x{img_h})", "info")

    def _set_camera_source_selection(self, value: str):
        value = (value or "").strip()
        legacy_names = {
            "none": "No Camera",
            "0": "Laptop Webcam",
            "1": "USB/HDMI Capture 1",
            "2": "USB/HDMI Capture 2",
            "rtsp://192.168.144.108:554/stream=1": "Skydroid C12 Live Feed (stream=1)",
        }
        value = legacy_names.get(value, value)
        for i in range(self._cam_source_input.count()):
            if value in (self._cam_source_input.itemText(i), str(self._cam_source_input.itemData(i))):
                self._cam_source_input.setCurrentIndex(i)
                return
        if value:
            self._cam_source_input.setCurrentText(value)

    def _selected_camera_source_value(self):
        text = self._cam_source_input.currentText().strip()
        idx = self._cam_source_input.currentIndex()
        if idx >= 0 and text == self._cam_source_input.itemText(idx):
            data = self._cam_source_input.itemData(idx)
            return "" if data is None else str(data).strip()
        return text

    # ─────────────── Slots ───────────────

    @pyqtSlot(bytes, str)
    def _on_frame_ready(self, img_bytes: bytes, source: str):
        self._processor.enqueue(img_bytes, source)
        # Save frame to mission folder if available
        if (
            self._record_mavlink_inputs
            and getattr(self, '_current_mission', None)
            and getattr(self, '_mission_manager', None)
        ):
            try:
                self._frame_save_count += 1
                fname = f"frame_{self._frame_save_count:04d}.jpg"
                self._mission_manager.export_buffer(self._current_mission, img_bytes, fname)
                self._mission_manager.append_jsonl(
                    self._current_mission,
                    "frame_manifest.jsonl",
                    {
                        "index": self._frame_save_count,
                        "filename": fname,
                        "source": source,
                        "received_at": datetime.now().isoformat(),
                        "size_bytes": len(img_bytes),
                    },
                )
            except Exception as e:
                # Log but don't block processing
                logger.debug(f"Failed to save frame to mission: {e}")

    @pyqtSlot(dict)
    def _on_telemetry_update(self, snap: dict):
        self._hud.update_telemetry(snap)
        if (
            self._record_mavlink_inputs
            and getattr(self, '_current_mission', None)
            and getattr(self, '_mission_manager', None)
        ):
            try:
                self._telemetry_save_count += 1
                self._mission_manager.append_jsonl(
                    self._current_mission,
                    "telemetry.jsonl",
                    {
                        "index": self._telemetry_save_count,
                        "received_at": datetime.now().isoformat(),
                        "telemetry": snap,
                    },
                )
            except Exception as e:
                logger.debug(f"Failed to save telemetry to mission: {e}")

    @pyqtSlot(list)
    def _on_raw_mavlink_messages(self, records: list):
        if not records:
            return
        if (
            self._record_mavlink_inputs
            and getattr(self, '_current_mission', None)
            and getattr(self, '_mission_manager', None)
        ):
            try:
                out = Path(self._current_mission).joinpath("mavlink_raw.jsonl")
                received_at = datetime.now().isoformat()
                with open(out, "a", encoding="utf-8") as f:
                    for record in records:
                        self._raw_mavlink_save_count += 1
                        json.dump(
                            {
                                "index": self._raw_mavlink_save_count,
                                "received_at": received_at,
                                "mavlink": record,
                            },
                            f,
                            default=str,
                        )
                        f.write("\n")
            except Exception as e:
                logger.debug(f"Failed to save raw MAVLink to mission: {e}")

    @pyqtSlot(dict)
    def _on_image_processed(self, result: dict):
        self._frame_count += 1
        self._fps_count += 1
        status = result.get("status", "error")
        src = result.get("source", "")
        if status == "success":
            self._log.log(f"[{self._frame_count}] {src} - processed", "success")
        else:
            self._log.log(f"[{self._frame_count}] {src} - {result.get('message', 'error')}", "error")
        # HUD is now refreshed inside _tick every 100 ms - no need to call here

    @pyqtSlot(np.ndarray)
    def _on_map_rendered(self, bgr_map: np.ndarray):
        self._map_canvas._map_resolution = self._service.map_resolution
        self._map_canvas._frame_count_overlay = self._frame_count
        self._map_canvas.update_map(bgr_map)

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        self._log.log(f"ERROR: {msg}", "error")

    @pyqtSlot(float)
    def _on_processing_time(self, ms: float):
        self._last_process_ms = ms

    @pyqtSlot(float)
    def _on_render_time(self, ms: float):
        self._last_render_ms = ms

    @pyqtSlot(int, int)
    def _on_sim_progress(self, current: int, total: int):
        pct = int(current / total * 100) if total else 0
        self._progress_bar.setValue(pct)
        self._progress_label.setText(f"FRAME {current}/{total}")

    @pyqtSlot()
    def _on_sim_finished(self):
        self._sim_worker = None
        if self._processor.queue_size > 0:
            self._folder_queue_active = True
            self._log.log("Folder frames loaded; processing remaining queue", "info")
            self._progress_label.setText("PROCESSING")
            self._start_btn.setText("■  STOP")
            self._start_btn.setObjectName("dangerBtn")
            self._start_btn.setStyleSheet(self._start_btn.styleSheet())
            return
        self._log.log("Folder replay complete", "success")
        self._progress_label.setText("COMPLETE")
        self._progress_bar.setValue(100)
        self._folder_queue_active = False
        self._start_btn.setText("▶  START")
        self._start_btn.setObjectName("accentBtn")
        self._start_btn.setStyleSheet(self._start_btn.styleSheet())

    def _on_theme_changed(self, theme_name: str):
        """Switch between dark and light themes."""
        theme_lower = theme_name.lower()
        _theme.set_theme(theme_lower)
        # TODO: For full theme switch, would need to rebuild all stylesheets
        # For now, apply a simple style tweak
        if theme_lower == "light":
            self._log.log("Switched to light theme (colors may appear off on target machine - check system theme)", "info")
        else:
            self._log.log("Switched to dark theme", "info")

    def _get_mavlink_endpoint_for_preference(self) -> str | None:
        """Get recommended MAVLink endpoint based on user preference."""
        pref = self._port_pref_combo.currentText()
        if "14551" in pref:
            return "udp:0.0.0.0:14551"
        elif "14550" in pref:
            return "udp:0.0.0.0:14550"
        return None  # auto-detect

    # ─────────────── Periodic refresh ───────────────

    def _tick(self):
        """10 Hz UI refresh - updates all dynamic panels."""
        # ── FPS (persisted between 1-second intervals) ──
        elapsed = self._fps_timer.elapsed()
        if elapsed > 1000:
            self._last_fps = self._fps_count / (elapsed / 1000.0)
            self._fps_count = 0
            self._fps_timer.restart()
        self._status_fps.setText(f"FPS: {self._last_fps:.1f}")

        # ── Tile / memory stats ──
        tiles = len(self._service.mapper.tiles)
        mem_mb = self._service.mapper.get_memory_usage() / (1024 * 1024)
        queue_len = self._processor.queue_size if self._processor else 0

        # ── GSD & coverage from mapper state ──
        gsd = 0.0
        coverage = 0.0
        if self._service.metrics_log:
            last_m = self._service.metrics_log[-1]
            alt = last_m.get("altitude", 0)
            if alt > 0:
                gsd = (self._service.sensor_width_mm * alt) / \
                      (self._service.focal_len_mm * self._service.img_width_px)
        # ── Coverage plot (update every ~1s - throttled by frame count) ──
        mapper = self._service.mapper
        fc = mapper.frame_count
        if fc > 0 and fc != self._coverage_plot._last_frame_count:
            self._coverage_plot._last_frame_count = fc
            cov_data = mapper.get_coverage_data()
            self._coverage_plot.set_data(cov_data)
            coverage = cov_data.get("area_m2", 0.0)
        elif tiles > 0:
            t_s = mapper.tile_size
            r = mapper.resolution
            coverage = tiles * (t_s * r) ** 2

        self._perf_panel.update_stats(
            fps=self._last_fps,
            process_ms=self._last_process_ms,
            render_ms=self._last_render_ms,
            tiles=tiles,
            memory=f"{mem_mb:.1f}",
            frames=self._frame_count,
            gsd=gsd,
            coverage=f"{coverage:.0f}",
            queue=queue_len,
        )

        # ── HUD refresh (simulation / upload mode) ──
        if not self._mav_worker and self._frame_count > 0:
            self._hud.set_from_mapper(self._service)

        if self._folder_queue_active and self._processor.queue_size == 0:
            self._folder_queue_active = False
            self._log.log("Folder replay complete", "success")
            self._progress_label.setText("COMPLETE")
            self._progress_bar.setValue(100)
            self._start_btn.setText("▶  START")
            self._start_btn.setObjectName("accentBtn")
            self._start_btn.setStyleSheet(self._start_btn.styleSheet())
            self._set_connected(False)

        # ── Uptime ──
        elapsed_s = (time.time() - self._service.session_start_time)
        m, s = divmod(int(elapsed_s), 60)
        h, m = divmod(m, 60)
        self._status_time.setText(f"Session: {h:02d}:{m:02d}:{s:02d}")

    def _set_connected(self, connected: bool, label: str = ""):
        if connected:
            self._status_conn.setText(f"⬤ {label}")
            self._status_conn.setStyleSheet(f"color: {C_GREEN}; font-weight: bold; padding: 0 12px;")
            self._status_mode.setText(f"Mode: {label}")
        else:
            self._status_conn.setText("⬤ DISCONNECTED")
            self._status_conn.setStyleSheet(f"color: {C_RED}; font-weight: bold; padding: 0 12px;")
            self._status_mode.setText(f"Mode: {self._mode_combo.currentText()}")

    # ─────────────── Cleanup ───────────────

    def closeEvent(self, event):
        self._save_settings()
        self._stop_current()
        self._processor.stop()
        event.accept()

    # ─────────────── Settings persistence ───────────────

    def _save_settings(self):
        """Save window state and all UI settings to QSettings."""
        s = self._settings
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/state", self.saveState())
        s.setValue("mode/index", self._mode_combo.currentIndex())
        s.setValue("map/satellite", self._satellite_cb.isChecked())
        s.setValue("map/flightpath", self._flightpath_cb.isChecked())
        s.setValue("map/pipeline", self._pipeline_combo.currentIndex())
        s.setValue("map/camera_profile", self._camera_profile_combo.currentText())
        s.setValue("map/custom_focal_len_mm", self._custom_focal_spin.value())
        s.setValue("map/custom_sensor_width_mm", self._custom_sensor_spin.value())
        s.setValue("map/custom_width_px", self._custom_width_spin.value())
        s.setValue("map/custom_height_px", self._custom_height_spin.value())
        s.setValue("map/resolution", self._res_spin.value())
        s.setValue("map/satellite_area", self._sat_area_spin.value())
        s.setValue("map/sim_speed", self._sim_speed_spin.value())
        s.setValue("mavlink/endpoint", self._mav_endpoint_input.text())
        s.setValue("mavlink/camera_source", self._selected_camera_source_value())
        s.setValue("mavlink/port_preference", self._port_pref_combo.currentText())
        s.setValue("mavlink/video_backend", self._video_backend_combo.currentText())
        s.setValue("mavlink/interval", self._mav_interval_spin.value())
        s.setValue("mavlink/video_delay", self._video_delay_spin.value())
        s.setValue("mavlink/attitude_fallback", self._attitude_fallback_combo.currentText())
        s.setValue("mavlink/allow_low_altitude", self._allow_low_alt_cb.isChecked())
        logger.debug("Settings saved")

    def _restore_settings(self):
        """Restore window state and UI settings from QSettings."""
        s = self._settings
        # Window geometry
        geom = s.value("window/geometry")
        if geom:
            self.restoreGeometry(geom)
        state = s.value("window/state")
        if state:
            self.restoreState(state)
        # UI controls
        idx = s.value("mode/index", 0, type=int)
        if 0 <= idx < self._mode_combo.count():
            self._mode_combo.setCurrentIndex(idx)
        self._satellite_cb.setChecked(s.value("map/satellite", True, type=bool))
        self._flightpath_cb.setChecked(s.value("map/flightpath", True, type=bool))
        pipeline_idx = s.value("map/pipeline", 0, type=int)
        if 0 <= pipeline_idx < self._pipeline_combo.count():
            self._pipeline_combo.setCurrentIndex(pipeline_idx)
        cam_prof = s.value("map/camera_profile", "")
        if cam_prof and self._camera_profile_combo.findText(cam_prof) >= 0:
            self._camera_profile_combo.setCurrentText(cam_prof)
        self._custom_focal_spin.setValue(s.value("map/custom_focal_len_mm", 24.0, type=float))
        self._custom_sensor_spin.setValue(s.value("map/custom_sensor_width_mm", 36.0, type=float))
        self._custom_width_spin.setValue(s.value("map/custom_width_px", 1280, type=int))
        self._custom_height_spin.setValue(s.value("map/custom_height_px", 720, type=int))
        self._on_camera_profile_changed(self._camera_profile_combo.currentText())
        self._res_spin.setValue(s.value("map/resolution", 0.5, type=float))
        self._sat_area_spin.setValue(s.value("map/satellite_area", 500, type=int))
        self._sim_speed_spin.setValue(s.value("map/sim_speed", 300, type=int))
        mav_ep = s.value("mavlink/endpoint", "")
        if mav_ep:
            self._mav_endpoint_input.setText(mav_ep)
        cam_src = s.value("mavlink/camera_source", "rtsp://192.168.144.108:554/stream=1")
        if cam_src:
            self._set_camera_source_selection(cam_src)
        port_pref = s.value("mavlink/port_preference", "QGC Compatible (14550)")
        if port_pref:
            self._port_pref_combo.setCurrentText(port_pref)
        video_backend = s.value("mavlink/video_backend", "Auto")
        if video_backend:
            self._video_backend_combo.setCurrentText(video_backend)
        attitude_fallback = s.value("mavlink/attitude_fallback", "Assume Stabilized Nadir")
        if attitude_fallback:
            self._attitude_fallback_combo.setCurrentText(attitude_fallback)
        # This deployment uses a stabilized gimbal. Avoid restoring the earlier
        # diagnostic aircraft-attitude setting because it causes jagged mosaics.
        self._attitude_fallback_combo.setCurrentText("Assume Stabilized Nadir")
        self._mav_interval_spin.setValue(s.value("mavlink/interval", 1000, type=int))
        self._video_delay_spin.setValue(s.value("mavlink/video_delay", 1000, type=int))
        self._allow_low_alt_cb.setChecked(s.value("mavlink/allow_low_altitude", False, type=bool))
        logger.debug("Settings restored")

    # ─────────────── Keyboard shortcuts ───────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._map_canvas.fit_map()
        elif event.key() == Qt.Key.Key_Space:
            self._on_start_stop()
        elif event.key() == Qt.Key.Key_R and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._on_reset()
        elif event.key() == Qt.Key.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
        else:
            super().keyPressEvent(event)


# ══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

def main():
    # ── Setup logging & crash handlers FIRST ──
    _setup_logging()
    sys.excepthook = _global_exception_handler
    threading.excepthook = _thread_exception_handler

    parser = argparse.ArgumentParser(description="SkyForge GCS")
    parser.add_argument("--mavlink", action="store_true", help="Auto-connect MAVLink on start")
    parser.add_argument("--simulate", action="store_true", help="Auto-start folder replay")
    parser.add_argument("--skip-license", action="store_true", help="Skip license check (dev mode)")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("SkyForge GCS")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("SkyForge")
    app.setStyle("Fusion")

    # Set app icon globally
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "skyforge.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # ── Splash screen ──
    splash = None
    splash_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "splash.png")
    if os.path.isfile(splash_path):
        splash_pixmap = QPixmap(splash_path)
    else:
        # Generate a simple branded splash if no image file exists
        splash_pixmap = QPixmap(480, 280)
        splash_pixmap.fill(QColor(C_BG))
        painter = QPainter(splash_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Title
        painter.setPen(QColor(C_ACCENT))
        painter.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
        painter.drawText(splash_pixmap.rect(), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                         "\n\nSKYFORGE GCS")
        # Version
        painter.setPen(QColor(C_TEXT_DIM))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(splash_pixmap.rect(), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         f"v{__version__}")
        # Loading text
        painter.setPen(QColor(C_TEXT_DIM))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(splash_pixmap.rect(),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                         "Loading...\n")
        painter.end()

    splash = QSplashScreen(splash_pixmap)
    splash.show()
    app.processEvents()

    # Update splash during heavy imports
    def splash_msg(msg: str):
        if splash:
            splash.showMessage(
                f"  {msg}", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                QColor(C_TEXT_DIM),
            )
            app.processEvents()

    splash_msg("Initializing configuration...")

    # Dark palette base (Fusion + stylesheet)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(C_PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(C_PANEL_LIGHT))
    palette.setColor(QPalette.ColorRole.Text, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(C_PANEL_LIGHT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C_ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(C_BG))
    app.setPalette(palette)
    app.setStyleSheet(DARK_STYLESHEET)

    splash_msg("Checking license...")

    # ── License check ──
    if not args.skip_license:
        try:
            from license_manager import show_license_dialog
            if not show_license_dialog(app):
                sys.exit(0)
        except ImportError:
            pass  # license_manager not bundled → skip

    splash_msg("Building interface...")

    window = GCSMainWindow(args)
    window.show()

    if splash:
        splash.finish(window)

    logger.info("SkyForge GCS started successfully")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
