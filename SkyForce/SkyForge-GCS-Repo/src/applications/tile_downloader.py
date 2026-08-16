import math
import os

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QDoubleSpinBox,
    QSpinBox,
    QProgressBar,
    QTextEdit,
    QMessageBox,
)

from backend.satellite import SatelliteTileProvider, _lat_lon_to_tile


def _estimate_tile_count(lat: float, lon: float, area_meters: float, zoom: int) -> int:
    half = area_meters / 2.0
    d_lat = half / 111_320.0
    d_lon = half / (111_320.0 * max(0.01, math.cos(math.radians(lat))))

    lat_min = lat - d_lat
    lat_max = lat + d_lat
    lon_min = lon - d_lon
    lon_max = lon + d_lon

    x_min, y_max = _lat_lon_to_tile(lat_min, lon_min, zoom)
    x_max, y_min = _lat_lon_to_tile(lat_max, lon_max, zoom)

    tx_min = max(min(x_min, x_max) - 1, 0)
    tx_max = max(x_min, x_max) + 1
    ty_min = max(min(y_min, y_max) - 1, 0)
    ty_max = max(y_min, y_max) + 1
    return max(0, (tx_max - tx_min + 1) * (ty_max - ty_min + 1))


class TileDownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    message = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, lat: float, lon: float, area_meters: int, zoom: int):
        super().__init__()
        self.lat = lat
        self.lon = lon
        self.area_meters = area_meters
        self.zoom = zoom
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            provider = SatelliteTileProvider(
                center_lat=self.lat,
                center_lon=self.lon,
                area_meters=self.area_meters,
                zoom=self.zoom,
            )
            total = (provider.tx_max - provider.tx_min + 1) * (provider.ty_max - provider.ty_min + 1)
            done = 0
            self.message.emit(f"Cache folder: {provider.cache_dir}")

            for ty in range(provider.ty_min, provider.ty_max + 1):
                for tx in range(provider.tx_min, provider.tx_max + 1):
                    if self._cancelled:
                        self.failed.emit("Download cancelled.")
                        return
                    provider._fetch_tile(tx, ty)
                    done += 1
                    self.progress.emit(done, total)

            provider._stitch()
            stats = provider.get_cache_stats()
            stats["cache_dir"] = provider.cache_dir
            stats["requested_tiles"] = total
            self.finished_ok.emit(stats)
        except Exception as exc:
            self.failed.emit(str(exc))


class TileDownloadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download Offline Tiles")
        self.setMinimumWidth(480)
        self._worker = None

        layout = QVBoxLayout(self)

        form = QGridLayout()
        form.addWidget(QLabel("Center Latitude"), 0, 0)
        self._lat_input = QDoubleSpinBox()
        self._lat_input.setRange(-85.0, 85.0)
        self._lat_input.setDecimals(8)
        self._lat_input.setValue(30.96375)
        form.addWidget(self._lat_input, 0, 1)

        form.addWidget(QLabel("Center Longitude"), 1, 0)
        self._lon_input = QDoubleSpinBox()
        self._lon_input.setRange(-180.0, 180.0)
        self._lon_input.setDecimals(8)
        self._lon_input.setValue(76.47593)
        form.addWidget(self._lon_input, 1, 1)

        form.addWidget(QLabel("Area Width (m)"), 2, 0)
        self._area_input = QSpinBox()
        self._area_input.setRange(100, 10000)
        self._area_input.setSingleStep(100)
        self._area_input.setValue(1000)
        form.addWidget(self._area_input, 2, 1)

        form.addWidget(QLabel("Zoom"), 3, 0)
        self._zoom_input = QSpinBox()
        self._zoom_input.setRange(15, 20)
        self._zoom_input.setValue(18)
        form.addWidget(self._zoom_input, 3, 1)

        self._estimate_label = QLabel("")
        form.addWidget(self._estimate_label, 4, 0, 1, 2)
        layout.addLayout(form)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        layout.addWidget(self._progress)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(120)
        layout.addWidget(self._log)

        buttons = QHBoxLayout()
        self._start_btn = QPushButton("Download")
        self._start_btn.clicked.connect(self._start_download)
        buttons.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel_download)
        self._cancel_btn.setEnabled(False)
        buttons.addWidget(self._cancel_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.close)
        buttons.addWidget(self._close_btn)
        layout.addLayout(buttons)

        for widget in (self._lat_input, self._lon_input, self._area_input, self._zoom_input):
            widget.valueChanged.connect(self._update_estimate)
        self._update_estimate()

    def _update_estimate(self):
        count = _estimate_tile_count(
            self._lat_input.value(),
            self._lon_input.value(),
            self._area_input.value(),
            self._zoom_input.value(),
        )
        self._estimate_label.setText(f"Estimated tiles: {count}")

    def _start_download(self):
        if self._worker is not None:
            return
        self._progress.setValue(0)
        self._log.clear()
        self._set_running(True)

        self._worker = TileDownloadWorker(
            self._lat_input.value(),
            self._lon_input.value(),
            self._area_input.value(),
            self._zoom_input.value(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.message.connect(self._append_log)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _cancel_download(self):
        if self._worker is not None:
            self._worker.cancel()
            self._append_log("Cancelling...")

    def _on_progress(self, done: int, total: int):
        pct = int(done * 100 / total) if total else 0
        self._progress.setValue(pct)
        self._progress.setFormat(f"{done}/{total} tiles")

    def _on_finished(self, stats: dict):
        self._append_log(
            "Download complete.\n"
            f"Fetched: {stats.get('fetched', 0)}\n"
            f"From cache: {stats.get('cache_hits', 0)}\n"
            f"Failures: {stats.get('fetch_failures', 0)}\n"
            f"Cached files: {stats.get('cached_files', 0)}\n"
            f"Cache size: {stats.get('cache_size_mb', 0)} MB"
        )
        self._set_running(False)
        self._worker = None

    def _on_failed(self, message: str):
        self._append_log(message)
        self._set_running(False)
        self._worker = None
        if message != "Download cancelled.":
            QMessageBox.warning(self, "Offline Tiles", message)

    def _append_log(self, message: str):
        self._log.append(message)

    def _set_running(self, running: bool):
        self._start_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._close_btn.setEnabled(not running)

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(3000)
        super().closeEvent(event)
