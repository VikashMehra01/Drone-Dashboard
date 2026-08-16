"""
Telemetry Logger - Logs flight telemetry data to mission folder as JSON.
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from threading import Lock


class TelemetryLogger:
    """Record telemetry snapshots to JSON and CSV files in the mission folder."""

    def __init__(self, mission_folder: Path | str):
        self.mission_folder = Path(mission_folder)
        self.mission_folder.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._records = []
        self._csv_file = self.mission_folder / "telemetry.csv"
        self._json_file = self.mission_folder / "telemetry.json"
        self._csv_writer = None
        self._initialize_csv()

    def _initialize_csv(self):
        """Create CSV file with headers."""
        try:
            with open(self._csv_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = [
                    'timestamp', 'lat', 'lon', 'alt_rel',
                    'vx', 'vy', 'vz', 'yaw', 'roll', 'pitch',
                    'satellites', 'gps_fix', 'hdop'
                ]
                self._csv_writer = csv.DictWriter(f, fieldnames=fieldnames)
                self._csv_writer.writeheader()
        except Exception as e:
            print(f"Failed to initialize telemetry CSV: {e}")

    def log_snapshot(self, snapshot: dict):
        """Record a telemetry snapshot."""
        with self._lock:
            try:
                record = {
                    'timestamp': datetime.now().isoformat(),
                    **snapshot
                }
                self._records.append(record)

                # Append to CSV (append mode, one line per call)
                if self._csv_writer:
                    with open(self._csv_file, 'a', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=record.keys())
                        writer.writerow(record)

            except Exception as e:
                print(f"Failed to log telemetry: {e}")

    def save_summary(self) -> dict:
        """Generate and save a summary of telemetry data."""
        with self._lock:
            if not self._records:
                return {}

            # Compute statistics
            lats = [r.get('lat', 0) for r in self._records]
            lons = [r.get('lon', 0) for r in self._records]
            alts = [r.get('alt_rel', 0) for r in self._records]
            sats_list = [r.get('satellites', 0) for r in self._records]
            fix_types = [r.get('gps_fix', 0) for r in self._records]

            summary = {
                'record_count': len(self._records),
                'start_time': self._records[0].get('timestamp', ''),
                'end_time': self._records[-1].get('timestamp', ''),
                'gps': {
                    'min_lat': min(lats) if lats else 0,
                    'max_lat': max(lats) if lats else 0,
                    'min_lon': min(lons) if lons else 0,
                    'max_lon': max(lons) if lons else 0,
                    'avg_lat': sum(lats) / len(lats) if lats else 0,
                    'avg_lon': sum(lons) / len(lons) if lons else 0,
                },
                'altitude': {
                    'min_m': min(alts) if alts else 0,
                    'max_m': max(alts) if alts else 0,
                    'avg_m': sum(alts) / len(alts) if alts else 0,
                },
                'gps_quality': {
                    'avg_satellites': sum(sats_list) / len(sats_list) if sats_list else 0,
                    'most_common_fix': max(set(fix_types), default=0),
                    'fix_types_distribution': {str(ft): fix_types.count(ft) for ft in set(fix_types)},
                },
            }

            # Save summary as JSON
            try:
                summary_file = self.mission_folder / "telemetry_summary.json"
                with open(summary_file, 'w', encoding='utf-8') as f:
                    json.dump(summary, f, indent=2, default=str)
            except Exception as e:
                print(f"Failed to save telemetry summary: {e}")

            return summary

    def get_all_records(self) -> list:
        """Return all recorded snapshots."""
        with self._lock:
            return self._records.copy()
