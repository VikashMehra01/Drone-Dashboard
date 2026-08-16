"""
drone_registry.py — In-memory store for launched drone configs + PIDs.

Persists as long as the backend process is running.
On server restart, the registry is cleared (and stream processors die too).
"""
from __future__ import annotations

# {drone_id: {"config": {...launch params}, "pid": int|None, "status": "active"|"stopped"}}
_registry: dict[str, dict] = {}


def register(drone_id: str, config: dict, pid: int) -> None:
    """Save or overwrite a drone's launch config and PID."""
    _registry[drone_id] = {"config": config, "pid": pid, "status": "active"}


def get(drone_id: str) -> dict | None:
    return _registry.get(drone_id)


def all_entries() -> dict[str, dict]:
    return dict(_registry)


def set_stopped(drone_id: str) -> None:
    if drone_id in _registry:
        _registry[drone_id]["status"] = "stopped"
        _registry[drone_id]["pid"] = None


def set_active(drone_id: str, pid: int) -> None:
    if drone_id in _registry:
        _registry[drone_id]["status"] = "active"
        _registry[drone_id]["pid"] = pid


def remove(drone_id: str) -> None:
    _registry.pop(drone_id, None)
