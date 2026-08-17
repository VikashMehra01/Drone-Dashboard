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
