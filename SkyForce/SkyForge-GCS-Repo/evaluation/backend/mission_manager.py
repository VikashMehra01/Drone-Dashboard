import os
import json
from pathlib import Path
from datetime import datetime
import cv2
import numpy as np

# Import config_manager from parent directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config_manager as cfg


class MissionManager:
    def __init__(self, base_dir: str | None = None):
        if base_dir is None:
            base_dir = cfg.SKYFORGE_DATA_DIR
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def create_mission(self, name: str | None = None) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = (name or "mission").strip().replace(" ", "_")
        folder = self.base.joinpath(f"{ts}_{safe}")
        folder.mkdir(parents=True, exist_ok=False)
        meta = {
            "name": name or f"mission_{ts}",
            "start_time": datetime.now().isoformat(),
            "notes": "",
        }
        with open(folder.joinpath("metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return folder

    def save_metadata(self, mission_path: Path, metadata: dict) -> None:
        p = Path(mission_path)
        p.joinpath("metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def export_image(self, mission_path: Path, image: np.ndarray, filename: str) -> Path:
        p = Path(mission_path)
        out = p.joinpath(filename)
        # Accept BGR numpy arrays (OpenCV format)
        cv2.imwrite(str(out), image)
        return out

    def export_buffer(self, mission_path: Path, data: bytes, filename: str) -> Path:
        out = Path(mission_path).joinpath(filename)
        with open(out, "wb") as f:
            f.write(data)
        return out

    def append_jsonl(self, mission_path: Path, filename: str, record: dict) -> Path:
        out = Path(mission_path).joinpath(filename)
        with open(out, "a", encoding="utf-8") as f:
            json.dump(record, f, default=str)
            f.write("\n")
        return out

    def list_missions(self):
        return sorted([p for p in self.base.iterdir() if p.is_dir()])
