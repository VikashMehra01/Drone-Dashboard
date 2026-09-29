"""Helpers for browser HLS stream paths."""

import hashlib


def stream_key(drone_id: str | None) -> str:
    """Return a filesystem-safe, stable directory key for a drone."""
    return hashlib.sha256((drone_id or "stream").encode("utf-8")).hexdigest()[:20]
