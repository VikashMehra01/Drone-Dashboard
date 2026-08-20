import os
import json
import sys
from pathlib import Path
from datetime import datetime

def _resolve_app_root() -> Path:
    """Return a persistent writable app root.

    In PyInstaller one-file builds, __file__ points inside a temporary _MEI
    extraction folder that is deleted when the app exits. Use the real EXE
    folder instead so mission data survives.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        try:
            exe_dir.mkdir(parents=True, exist_ok=True)
            probe = exe_dir / ".skyforge_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return exe_dir
        except Exception:
            documents = Path.home() / "Documents" / "SkyForge GCS"
            documents.mkdir(parents=True, exist_ok=True)
            return documents
    return Path(__file__).resolve().parent


ROOT = _resolve_app_root()
SKYFORGE_LOG_DIR = str(ROOT.joinpath("logs"))
SKYFORGE_DATA_DIR = str(ROOT.joinpath("data"))

os.makedirs(SKYFORGE_LOG_DIR, exist_ok=True)
os.makedirs(SKYFORGE_DATA_DIR, exist_ok=True)


class ConfigManager:
    """Simple JSON-backed config manager for project settings."""

    def __init__(self, filename: str = "config.json"):
        self.path = Path(SKYFORGE_DATA_DIR) / filename
        if not self.path.exists():
            self._data = {}
            self._write()
        else:
            self._read()

    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception:
            self._data = {}

    def _write(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception:
            pass

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self._write()
