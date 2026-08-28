"""
drone_registry.py — portable process-lifecycle helpers for CV worker subprocesses.

The `drone_configs` DB table (see app/db.py, columns `pid` + `status`) is the
single source of truth for whether a drone's stream_processor.py is running.
This module only wraps `psutil` so liveness checks and termination behave the
same on Linux, macOS, and Windows — no more OS-specific pgrep/PowerShell/
taskkill branching, and no more separate in-memory registry or PID file that
can drift out of sync with the DB.
"""
from __future__ import annotations

import psutil


def is_alive(pid: int | None) -> bool:
    """True if `pid` refers to a process that's actually doing something.

    `psutil.pid_exists()` alone isn't enough: a crashed child whose parent
    (this backend) never called wait()/poll() on it stays in the process
    table as a zombie — pid_exists() still returns True for it, even though
    it's doing no useful work (this is exactly what happens to a stream_
    processor.py that exits, e.g. from a bad --source path, while the
    backend that spawned it keeps running under --reload).
    """
    if not pid or not psutil.pid_exists(pid):
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def terminate(pid: int | None, timeout: float = 5.0) -> bool:
    """
    Gracefully terminate the process at `pid`, escalating to a hard kill if it
    doesn't exit within `timeout` seconds. Works identically on every OS.

    Returns True if a live process was found and terminated, False if it was
    already gone — not running, or a zombie (already exited, just not yet
    reaped by its parent — nothing left to signal) — or `pid` is falsy.
    """
    if not is_alive(pid):
        return False
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            proc.kill()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def find_worker_pids(drone_id: str) -> list[int]:
    """Every live `stream_processor.py --drone-id <drone_id>` process.

    The DB's `pid` column can drift — a worker relaunched out-of-band, a stale
    row after a crash, or (as actually happened) a feed that dropped and is
    reconnecting forever while the dashboard already shows it 'idle'. Scanning
    the process table by the `--drone-id` argument finds them all regardless of
    what the DB thinks.
    """
    matches: list[int] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not any("stream_processor.py" in str(part) for part in cmdline):
            continue
        for i, part in enumerate(cmdline):
            if part == "--drone-id" and i + 1 < len(cmdline) and cmdline[i + 1] == drone_id:
                matches.append(proc.info["pid"])
                break
    return matches


def terminate_by_drone_id(drone_id: str, timeout: float = 5.0) -> list[int]:
    """Kill every stream_processor.py worker for `drone_id`. Returns killed pids."""
    killed: list[int] = []
    for pid in find_worker_pids(drone_id):
        if terminate(pid, timeout=timeout):
            killed.append(pid)
    return killed
