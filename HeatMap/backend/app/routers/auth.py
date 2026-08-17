"""
auth.py — Authentication + admin management endpoints.

POST   /api/auth/login                       → returns JWT
GET    /api/auth/me                          → current user info
GET    /api/auth/users                       → (admin) list all users
POST   /api/auth/users                       → (admin) create user
DELETE /api/auth/users/{username}            → (admin) delete user
PATCH  /api/auth/users/{username}/password   → (admin) change password
GET    /api/auth/drones                      → (admin) list all drones
DELETE /api/auth/drones/{drone_id}           → (admin) remove from active streams
POST   /api/auth/drones/launch               → (admin) launch stream processor
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.db import get_db_cursor
from app.utils.security import hash_password, verify_password, create_access_token, decode_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "member"


class ChangePasswordRequest(BaseModel):
    new_password: str


class AddDroneRequest(BaseModel):
    drone_id: str
    drone_name: str
    source: str
    latitude: float
    longitude: float
    altitude: float = 100.0
    zone: str = "Live Stream Zone"
    fps: int = 5
    loop: bool = False
    model: str = "sdnet"   # "sdnet" | "yolo"
    device: str = "cpu"    # "cpu" | "cuda"


class EditDroneRequest(BaseModel):
    drone_name: Optional[str] = None
    source: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    zone: Optional[str] = None
    fps: Optional[int] = None
    loop: Optional[bool] = None
    model: Optional[str] = None
    device: Optional[str] = None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_user(username: str) -> Optional[dict]:
    with get_db_cursor() as (_, cur):
        cur.execute("SELECT id, username, hashed_password, role FROM users WHERE username = ?", (username,))
        return cur.fetchone()


def _list_users() -> list:
    with get_db_cursor() as (_, cur):
        cur.execute("SELECT id, username, role, created_at FROM users ORDER BY id ASC")
        return cur.fetchall()


def _count_admins() -> int:
    with get_db_cursor() as (_, cur):
        cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'")
        row = cur.fetchone()
        return int(row["cnt"]) if row else 0


def _create_user(username: str, password: str, role: str) -> None:
    with get_db_cursor() as (_, cur):
        cur.execute(
            "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
            (username, hash_password(password), role),
        )


def _delete_user(username: str) -> None:
    with get_db_cursor() as (_, cur):
        cur.execute("DELETE FROM users WHERE username = ?", (username,))


def _update_password(username: str, new_password: str) -> None:
    with get_db_cursor() as (_, cur):
        cur.execute(
            "UPDATE users SET hashed_password = ? WHERE username = ?",
            (hash_password(new_password), username),
        )


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@router.post("/login")
async def login(body: LoginRequest):
    user = _get_user(body.username)
    if not user or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer", "role": user["role"], "username": user["username"]}


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {"username": current_user["sub"], "role": current_user["role"]}


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_users(_admin: dict = Depends(require_admin)):
    users = _list_users()
    return [
        {"id": u.get("id"), "username": u["username"], "role": u["role"],
         "created_at": str(u.get("created_at", ""))}
        for u in users
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_member(body: CreateUserRequest, _admin: dict = Depends(require_admin)):
    if body.role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'member'")
    if body.role == "admin" and _count_admins() >= 1:
        raise HTTPException(status_code=409, detail="There can only be one admin account.")
    existing = _get_user(body.username)
    if existing:
        raise HTTPException(status_code=409, detail=f"Username '{body.username}' already exists")
    _create_user(body.username, body.password, body.role)
    return {"message": f"User '{body.username}' created successfully", "role": body.role}


@router.delete("/users/{username}", status_code=status.HTTP_200_OK)
async def delete_user(username: str, admin: dict = Depends(require_admin)):
    if username == admin["sub"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    target = _get_user(username)
    if not target:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
    if target["role"] == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete the admin account.")
    _delete_user(username)
    return {"message": f"User '{username}' deleted."}


@router.patch("/users/{username}/password", status_code=status.HTTP_200_OK)
async def change_password(username: str, body: ChangePasswordRequest, _admin: dict = Depends(require_admin)):
    if not body.new_password or len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")
    target = _get_user(username)
    if not target:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
    _update_password(username, body.new_password)
    return {"message": f"Password for '{username}' updated."}


# ---------------------------------------------------------------------------
# Drone management (admin only)
# ---------------------------------------------------------------------------

import os as _os
import time as _time
from app import drone_registry as _reg


def _resolve_paths():
    from pathlib import Path
    backend_dir = Path(__file__).resolve().parents[2]
    project_root = backend_dir.parent
    drone_dir = project_root / "cv_pipeline"
    venv_py_win = backend_dir / "venv" / "Scripts" / "python.exe"
    venv_py_unix = backend_dir / "venv" / "bin" / "python"
    python_exe = str(venv_py_win) if venv_py_win.exists() else (
        str(venv_py_unix) if venv_py_unix.exists() else sys.executable
    )
    return drone_dir, drone_dir / "stream_processor.py", python_exe


def _load_stream_config():
    """Load cv_pipeline/stream_config.py as a module. Loaded directly from the
    file rather than a package import so this doesn't require torch/cv2/etc.
    to be installed in the backend's venv; stream_config.py itself is pure
    stdlib.
    """
    import importlib.util
    drone_dir, _, _ = _resolve_paths()
    spec = importlib.util.spec_from_file_location("cv_pipeline_stream_config", drone_dir / "stream_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_model_presets() -> dict:
    """cv_pipeline/stream_config.py's MODEL_PRESETS — the single source of
    truth for which detection models are available (see that file for the
    list)."""
    return _load_stream_config().MODEL_PRESETS


def _validate_source(source: str, drone_dir) -> str | None:
    """Returns an error message if `source` is a local file path that
    doesn't exist, or None if it's fine (a live stream URL, or a file that
    exists).

    Without this check, a bad local path (e.g. a typo) only surfaces as a
    crash deep inside stream_processor.py — but that happens *after* the
    detection model finishes loading (several seconds), well past the 1s
    crash-check window in launch_drone/resume_drone below. The API call
    reports success, the drone just silently never goes active, and nothing
    in the UI ever explains why. Checking here catches it immediately and
    returns a clear error instead.
    """
    from urllib.parse import urlparse
    if urlparse(source).scheme.lower() in _load_stream_config().LIVE_URL_SCHEMES:
        return None
    from pathlib import Path
    resolved = (drone_dir / source).resolve()
    if not resolved.is_file():
        return f"Video file not found: '{source}' (resolved to {resolved})"
    return None


@router.get("/models")
async def list_models(_admin: dict = Depends(require_admin)):
    """(Admin) List available detection models, sourced from cv_pipeline/stream_config.py."""
    try:
        presets = _load_model_presets()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load model list: {e}")
    return [{"key": key, "label": preset.get("label", key)} for key, preset in presets.items()]


def _build_cmd(python_exe: str, processor, config: dict) -> list:
    return [
        python_exe, str(processor),
        "--source", config["source"],
        "--fps", str(config["fps"]),
        "--drone-id", config["drone_id"],
        "--drone-name", config["drone_name"],
        "--zone", config["zone"],
        "--latitude", str(config["latitude"]),
        "--longitude", str(config["longitude"]),
        "--altitude", str(config["altitude"]),
        "--loop", "true" if config.get("loop") else "false",
        "--model", config.get("model", "sdnet"),
        "--device", config.get("device", "cpu"),
    ]


def _spawn(cmd: list, drone_dir, log_path) -> subprocess.Popen:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    log_file = open(str(log_path), "a")
    proc = subprocess.Popen(
        cmd,
        cwd=str(drone_dir),
        stdout=log_file,
        stderr=log_file,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        env={**_os.environ, "PYTHONUTF8": "1"},
    )
    log_file.close()
    return proc


# ── DB helpers for drone configs ─────────────────────────────────────────────

def _db_save_config(config: dict, pid: int | None, status: str = "active") -> None:
    """Upsert drone config + pid + status into drone_configs table."""
    try:
        with get_db_cursor() as (_, cur):
            cur.execute("""
                INSERT INTO drone_configs
                    (drone_id, drone_name, source, latitude, longitude,
                     altitude, zone, fps, loop, model, device, pid, status, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,strftime('%s','now'))
                ON CONFLICT (drone_id) DO UPDATE SET
                    drone_name=excluded.drone_name, source=excluded.source,
                    latitude=excluded.latitude, longitude=excluded.longitude,
                    altitude=excluded.altitude, zone=excluded.zone,
                    fps=excluded.fps, loop=excluded.loop,
                    model=excluded.model, device=excluded.device,
                    pid=excluded.pid, status=excluded.status, updated_at=strftime('%s','now')
            """, (
                config["drone_id"], config["drone_name"], config["source"],
                config["latitude"], config["longitude"], config["altitude"],
                config["zone"], config["fps"], config.get("loop", False),
                config.get("model", "sdnet"), config.get("device", "cpu"), pid, status,
            ))
    except Exception as e:
        print(f"[DB] drone_configs upsert failed: {e}")


def _db_get_config(drone_id: str) -> dict | None:
    """Fetch a single drone config row as dict, or None."""
    try:
        with get_db_cursor() as (_, cur):
            cur.execute("SELECT * FROM drone_configs WHERE drone_id = ?", (drone_id,))
            return cur.fetchone()
    except Exception as e:
        print(f"[DB] drone_configs fetch failed: {e}")
        return None


def _db_set_active(drone_id: str, pid: int) -> None:
    try:
        with get_db_cursor() as (_, cur):
            cur.execute(
                "UPDATE drone_configs SET status=?, pid=?, updated_at=strftime('%s','now') WHERE drone_id=?",
                ("active", pid, drone_id)
            )
    except Exception as e:
        print(f"[DB] drone_configs set-active failed: {e}")


def _db_set_stopped(drone_id: str) -> None:
    try:
        with get_db_cursor() as (_, cur):
            cur.execute(
                "UPDATE drone_configs SET status=?, pid=NULL, updated_at=strftime('%s','now') WHERE drone_id=?",
                ("stopped", drone_id)
            )
    except Exception as e:
        print(f"[DB] drone_configs set-stopped failed: {e}")


def _db_load_all_configs() -> dict[str, dict]:
    """Return all drone configs as {drone_id: row_dict}."""
    try:
        with get_db_cursor() as (_, cur):
            cur.execute("SELECT * FROM drone_configs")
            return {r["drone_id"]: r for r in cur.fetchall()}
    except Exception as e:
        print(f"[DB] drone_configs load all failed: {e}")
        return {}


def reconcile_drone_statuses() -> None:
    """
    Called once at backend startup. `drone_configs.status` can say "active"
    from before the backend last restarted even though the OS process behind
    it is long gone (subprocesses aren't tied to the backend's lifetime, but
    they don't reliably survive forever either). Correct any such stale rows
    so the dashboard doesn't show phantom "active" drones after a restart.
    """
    try:
        configs = _db_load_all_configs()
    except Exception as exc:
        print(f"[auth] reconcile_drone_statuses: could not load configs: {exc}")
        return

    for drone_id, config in configs.items():
        if config.get("status") == "active" and not _reg.is_alive(config.get("pid")):
            _db_set_stopped(drone_id)
            print(f"[auth] Reconciled stale 'active' status for drone '{drone_id}' (process not running).")


@router.get("/drones")
async def list_drones_admin(_admin: dict = Depends(require_admin)):
    """(Admin) List all drones — active and stopped (from DB configs)."""
    from app.routers.drone import _build_drones_payload
    drones = _build_drones_payload()
    configs = _db_load_all_configs()

    # Enrich each drone with the DB config, verifying "active" against the
    # real OS process rather than trusting the stored status blindly.
    for d in drones:
        config = configs.get(d["id"])
        if config:
            pid = config.get("pid")
            alive = _reg.is_alive(pid)
            if config.get("status") == "active" and not alive:
                _db_set_stopped(d["id"])  # self-heal a stale row
            d["registry_status"] = "active" if alive else "stopped"
            d["pid"] = pid if alive else None
            d["config"] = config
        else:
            d["registry_status"] = "stopped" if d["status"] == "idle" else d["status"]
            d["pid"] = None
            d["config"] = None

    return drones


@router.delete("/drones/{drone_id}", status_code=status.HTTP_200_OK)
async def delete_drone(drone_id: str, _admin: dict = Depends(require_admin)):
    """(Admin) Stop (if running) and permanently delete drone config from DB."""
    from app.routers.density import active_streams

    config = _db_get_config(drone_id)
    _reg.terminate(config.get("pid") if config else None)

    # Remove from active streams
    keys = [k for k, v in active_streams.items() if v.get("drone_id") == drone_id]
    for k in keys:
        del active_streams[k]

    # Delete from DB
    try:
        with get_db_cursor() as (_, cur):
            cur.execute("DELETE FROM drone_configs WHERE drone_id = ?", (drone_id,))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB delete failed: {e}")

    return {"message": f"Drone '{drone_id}' deleted permanently."}


@router.patch("/drones/{drone_id}", status_code=status.HTTP_200_OK)
async def update_drone(drone_id: str, body: EditDroneRequest, _admin: dict = Depends(require_admin)):
    """(Admin) Update details of a saved drone config in the DB."""
    
    # Extract only provided fields
    updates = body.dict(exclude_unset=True)
    if not updates:
        return {"message": "No fields provided to update."}

    # Check if drone exists
    config = _db_get_config(drone_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' not found in DB.")

    # Build SET clause dynamically
    set_clauses = []
    values = []
    for k, v in updates.items():
        set_clauses.append(f"{k} = ?")
        values.append(v)

    values.append(drone_id)
    query = f"UPDATE drone_configs SET {', '.join(set_clauses)} WHERE drone_id = ?"

    try:
        with get_db_cursor() as (_, cur):
            cur.execute(query, tuple(values))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB update failed: {e}")

    return {"message": f"Drone '{drone_id}' configuration updated."}


@router.post("/drones/stop/{drone_id}", status_code=status.HTTP_200_OK)
async def stop_drone(drone_id: str, _admin: dict = Depends(require_admin)):
    """(Admin) Stop the stream processor using its DB-recorded PID."""
    from app.routers.density import active_streams

    config = _db_get_config(drone_id)
    pid = config.get("pid") if config else None
    killed = _reg.terminate(pid)

    keys = [k for k, v in active_streams.items() if v.get("drone_id") == drone_id]
    for k in keys:
        del active_streams[k]

    _db_set_stopped(drone_id)

    if killed:
        return {"message": f"Drone '{drone_id}' stopped (killed PID {pid}).", "killed_pids": [pid]}
    else:
        return {"message": f"Drone '{drone_id}': no running process found, stream data cleared.", "killed_pids": []}


@router.post("/drones/resume/{drone_id}", status_code=status.HTTP_202_ACCEPTED)
async def resume_drone(drone_id: str, _admin: dict = Depends(require_admin)):
    """(Admin) Re-launch a previously stopped drone using its saved config."""
    drone_dir, processor, python_exe = _resolve_paths()

    config = _db_get_config(drone_id)
    if not config:
        raise HTTPException(status_code=404,
            detail=f"No saved config for '{drone_id}'. Use Add Drone to launch it first.")

    if _reg.is_alive(config.get("pid")):
        raise HTTPException(status_code=409,
            detail=f"Drone '{drone_id}' is already running (PID {config['pid']}).")

    if not processor.exists():
        raise HTTPException(status_code=404, detail="stream_processor.py not found.")

    source_error = _validate_source(config["source"], drone_dir)
    if source_error:
        raise HTTPException(status_code=400, detail=source_error)

    cmd = _build_cmd(python_exe, processor, config)
    log_path = drone_dir / f"drone_{drone_id}.log"

    try:
        proc = _spawn(cmd, drone_dir, log_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start process: {exc}")

    _time.sleep(1)
    if proc.poll() is not None:
        try:
            error_text = log_path.read_text(errors="replace")[-600:]
        except Exception:
            error_text = "(unreadable)"
        raise HTTPException(status_code=500,
            detail=f"Stream processor crashed on resume:\n{error_text}")

    _db_set_active(drone_id, proc.pid)
    return {
        "message": f"Drone '{drone_id}' resumed (PID {proc.pid}).",
        "drone_id": drone_id,
        "pid": proc.pid,
    }


# ---------------------------------------------------------------------------
# Drone launch (admin only) — must be AFTER /drones/{drone_id} to avoid route clash
# ---------------------------------------------------------------------------

@router.post("/drones/launch", status_code=status.HTTP_202_ACCEPTED)
async def launch_drone(body: AddDroneRequest, _admin: dict = Depends(require_admin)):
    """(Admin) Launch a detached stream_processor.py for a new drone."""
    drone_dir, processor, python_exe = _resolve_paths()
    if not processor.exists():
        raise HTTPException(status_code=404, detail=f"stream_processor.py not found at {processor}")

    source_error = _validate_source(body.source, drone_dir)
    if source_error:
        raise HTTPException(status_code=400, detail=source_error)

    config = {
        "drone_id": body.drone_id, "drone_name": body.drone_name,
        "source": body.source, "latitude": body.latitude, "longitude": body.longitude,
        "altitude": body.altitude, "zone": body.zone, "fps": body.fps,
        "loop": body.loop, "model": body.model, "device": body.device,
    }
    cmd = _build_cmd(python_exe, processor, config)
    log_path = drone_dir / f"drone_{body.drone_id}.log"

    try:
        proc = _spawn(cmd, drone_dir, log_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start process: {exc}")

    _time.sleep(1)
    if proc.poll() is not None:
        try:
            error_text = log_path.read_text(errors="replace")[-800:]
        except Exception:
            error_text = "(could not read log)"
        raise HTTPException(status_code=500,
            detail=f"Stream processor crashed immediately. Log ({log_path.name}):\n{error_text}")

    _db_save_config(config, pid=proc.pid, status="active")
    return {
        "message": f"Drone '{body.drone_name}' ({body.drone_id}) launched (PID {proc.pid}).",
        "drone_id": body.drone_id,
        "pid": proc.pid,
        "log": str(log_path),
    }
