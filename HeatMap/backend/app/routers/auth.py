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

from app.db import get_db_cursor, is_using_memory_db
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
    with get_db_cursor(dict_rows=True) as (_, cur):
        cur.execute("SELECT id, username, hashed_password, role FROM users WHERE username = %s", (username,))
        return cur.fetchone()


def _list_users() -> list:
    with get_db_cursor(dict_rows=True) as (_, cur):
        cur.execute("SELECT id, username, role, created_at FROM users ORDER BY id ASC")
        return cur.fetchall()


def _count_admins() -> int:
    with get_db_cursor(dict_rows=True) as (_, cur):
        cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'")
        row = cur.fetchone()
        return int(row["cnt"]) if row else 0


def _create_user(username: str, password: str, role: str) -> None:
    with get_db_cursor(dict_rows=True) as (_, cur):
        cur.execute(
            "INSERT INTO users (username, hashed_password, role) VALUES (%s, %s, %s)",
            (username, hash_password(password), role),
        )


def _delete_user(username: str) -> None:
    with get_db_cursor(dict_rows=True) as (_, cur):
        cur.execute("DELETE FROM users WHERE username = %s", (username,))


def _update_password(username: str, new_password: str) -> None:
    with get_db_cursor(dict_rows=True) as (_, cur):
        cur.execute(
            "UPDATE users SET hashed_password = %s WHERE username = %s",
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

def _db_save_config(config: dict, status: str = "active") -> None:
    """Upsert drone config + status into drone_configs table."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                INSERT INTO drone_configs
                    (drone_id, drone_name, source, latitude, longitude,
                     altitude, zone, fps, loop, model, device, status, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (drone_id) DO UPDATE SET
                    drone_name=EXCLUDED.drone_name, source=EXCLUDED.source,
                    latitude=EXCLUDED.latitude, longitude=EXCLUDED.longitude,
                    altitude=EXCLUDED.altitude, zone=EXCLUDED.zone,
                    fps=EXCLUDED.fps, loop=EXCLUDED.loop,
                    model=EXCLUDED.model, device=EXCLUDED.device,
                    status=EXCLUDED.status, updated_at=NOW()
            """, (
                config["drone_id"], config["drone_name"], config["source"],
                config["latitude"], config["longitude"], config["altitude"],
                config["zone"], config["fps"], config.get("loop", False),
                config.get("model", "sdnet"), config.get("device", "cpu"), status
            ))
    except Exception as e:
        print(f"[DB] drone_configs upsert failed: {e}")


def _db_get_config(drone_id: str) -> dict | None:
    """Fetch a single drone config row as dict, or None."""
    try:
        with get_db_cursor(dict_rows=True) as (_, cur):
            cur.execute("SELECT * FROM drone_configs WHERE drone_id = %s", (drone_id,))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)
    except Exception as e:
        print(f"[DB] drone_configs fetch failed: {e}")
        return None


def _db_set_status(drone_id: str, status: str) -> None:
    try:
        with get_db_cursor() as (_, cur):
            cur.execute(
                "UPDATE drone_configs SET status=%s, updated_at=NOW() WHERE drone_id=%s",
                (status, drone_id)
            )
    except Exception as e:
        print(f"[DB] drone_configs status update failed: {e}")


def _db_load_all_configs() -> dict[str, dict]:
    """Return all drone configs as {drone_id: row_dict}."""
    try:
        with get_db_cursor(dict_rows=True) as (_, cur):
            cur.execute("SELECT * FROM drone_configs")
            rows = cur.fetchall()
            return {r["drone_id"]: dict(r) for r in rows}
    except Exception as e:
        print(f"[DB] drone_configs load all failed: {e}")
        return {}


# ── PID file (disk only — PID is ephemeral, doesn't belong in DB) ─────────────

def _pid_path(drone_dir, drone_id: str):
    from pathlib import Path
    return Path(drone_dir) / f"drone_{drone_id}.pid"


def _write_pid(drone_dir, drone_id: str, pid: int) -> None:
    _pid_path(drone_dir, drone_id).write_text(str(pid))


def _read_pid(drone_dir, drone_id: str) -> int | None:
    try:
        return int(_pid_path(drone_dir, drone_id).read_text().strip())
    except Exception:
        return None


def _delete_pid(drone_dir, drone_id: str) -> None:
    try:
        _pid_path(drone_dir, drone_id).unlink(missing_ok=True)
    except Exception:
        pass


@router.get("/drones")
async def list_drones_admin(_admin: dict = Depends(require_admin)):
    """(Admin) List all drones — active and stopped (from DB configs)."""
    from app.routers.drone import _build_drones_payload
    drones = _build_drones_payload()

    # Enrich each drone with registry info (pid, precise status)
    for d in drones:
        entry = _reg.get(d["id"])
        if entry:
            d["registry_status"] = entry["status"]
            d["pid"] = entry["pid"]
            d["config"] = entry["config"]
        else:
            d["registry_status"] = "stopped" if d["status"] == "idle" else d["status"]
            d["pid"] = None
            d["config"] = _db_get_config(d["id"])

    return drones


@router.delete("/drones/{drone_id}", status_code=status.HTTP_200_OK)
async def delete_drone(drone_id: str, _admin: dict = Depends(require_admin)):
    """(Admin) Stop (if running) and permanently delete drone config from DB."""
    from app.routers.density import active_streams
    drone_dir, _, _ = _resolve_paths()

    # Kill process if running (same logic as stop)
    if sys.platform == "win32":
        ps_script = (
            f"Get-WmiObject Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*stream_processor.py*' -and "
            f"$_.CommandLine -like '*{drone_id}*' }} | "
            f"Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=10
            )
            for p in result.stdout.splitlines():
                if p.strip().isdigit():
                    subprocess.call(["taskkill", "/F", "/T", "/PID", p.strip()],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    else:
        try:
            import signal as _sig
            result = subprocess.run(["pgrep", "-f", f"stream_processor.py.*{drone_id}"],
                                    capture_output=True, text=True)
            for p in result.stdout.splitlines():
                if p.strip().isdigit():
                    _os.kill(int(p.strip()), _sig.SIGTERM)
        except Exception:
            pass

    # Clean up PID file
    _delete_pid(drone_dir, drone_id)

    # Remove from active streams
    keys = [k for k, v in active_streams.items() if v.get("drone_id") == drone_id]
    for k in keys:
        del active_streams[k]

    # Remove from in-memory registry
    _reg.remove(drone_id)

    # Delete from DB
    try:
        with get_db_cursor() as (_, cur):
            cur.execute("DELETE FROM drone_configs WHERE drone_id = %s", (drone_id,))
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
        set_clauses.append(f"{k} = %s")
        values.append(v)
    
    values.append(drone_id)
    query = f"UPDATE drone_configs SET {', '.join(set_clauses)} WHERE drone_id = %s"

    try:
        with get_db_cursor() as (_, cur):
            cur.execute(query, tuple(values))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB update failed: {e}")

    # Also update in-memory registry if it happens to be loaded
    entry = _reg.get(drone_id)
    if entry and entry.get("config"):
        for k, v in updates.items():
            entry["config"][k] = v

    return {"message": f"Drone '{drone_id}' configuration updated."}


@router.post("/drones/stop/{drone_id}", status_code=status.HTTP_200_OK)
async def stop_drone(drone_id: str, _admin: dict = Depends(require_admin)):
    """(Admin) Kill the stream processor by searching running processes for drone_id."""
    from app.routers.density import active_streams
    drone_dir, _, _ = _resolve_paths()

    killed_pids = []

    if sys.platform == "win32":
        # Use PowerShell to find python processes whose cmdline contains both
        # stream_processor.py AND the drone-id string, then kill them.
        ps_script = (
            f"Get-WmiObject Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*stream_processor.py*' -and "
            f"$_.CommandLine -like '*{drone_id}*' }} | "
            f"Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=10
            )
            pids = [int(p.strip()) for p in result.stdout.splitlines() if p.strip().isdigit()]
            for pid in pids:
                subprocess.call(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                killed_pids.append(pid)
        except Exception as e:
            pass  # fall through to PID-file fallback

        # Fallback: try stored PID file if powershell found nothing
        if not killed_pids:
            pid = _read_pid(drone_dir, drone_id)
            if pid:
                subprocess.call(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                killed_pids.append(pid)
    else:
        # Unix: use pgrep to find matching processes
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"stream_processor.py.*{drone_id}"],
                capture_output=True, text=True
            )
            import signal as _signal
            for pid_str in result.stdout.splitlines():
                pid = int(pid_str.strip())
                _os.kill(pid, _signal.SIGTERM)
                killed_pids.append(pid)
        except Exception:
            pass

    # Always clean up PID file and active streams
    _delete_pid(drone_dir, drone_id)
    keys = [k for k, v in active_streams.items() if v.get("drone_id") == drone_id]
    for k in keys:
        del active_streams[k]

    # Update DB status and in-memory registry
    _db_set_status(drone_id, "stopped")
    _reg.set_stopped(drone_id)

    if killed_pids:
        return {"message": f"Drone '{drone_id}' stopped (killed PIDs: {killed_pids}).", "killed_pids": killed_pids}
    else:
        return {"message": f"Drone '{drone_id}': no running process found, stream data cleared.", "killed_pids": []}


@router.post("/drones/resume/{drone_id}", status_code=status.HTTP_202_ACCEPTED)
async def resume_drone(drone_id: str, _admin: dict = Depends(require_admin)):
    """(Admin) Re-launch a previously stopped drone using its saved config."""
    drone_dir, processor, python_exe = _resolve_paths()

    # Config: prefer in-memory registry, fall back to DB
    entry = _reg.get(drone_id)
    config = (entry["config"] if entry else None) or _db_get_config(drone_id)
    if not config:
        raise HTTPException(status_code=404,
            detail=f"No saved config for '{drone_id}'. Use Add Drone to launch it first.")

    if entry and entry["status"] == "active":
        raise HTTPException(status_code=409,
            detail=f"Drone '{drone_id}' is already running (PID {entry['pid']}).")

    if not processor.exists():
        raise HTTPException(status_code=404, detail="stream_processor.py not found.")

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

    _write_pid(drone_dir, drone_id, proc.pid)
    _db_set_status(drone_id, "active")   # update DB status
    _reg.set_active(drone_id, proc.pid)
    if drone_id not in _reg.all_entries():
        _reg.register(drone_id, config, proc.pid)
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

    _write_pid(drone_dir, body.drone_id, proc.pid)
    _db_save_config(config, status="active")   # persist config + status to DB
    _reg.register(body.drone_id, config, proc.pid)
    return {
        "message": f"Drone '{body.drone_name}' ({body.drone_id}) launched (PID {proc.pid}).",
        "drone_id": body.drone_id,
        "pid": proc.pid,
        "log": str(log_path),
    }
