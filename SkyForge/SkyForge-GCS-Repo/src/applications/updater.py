"""
Small update helper for SkyForge GCS.

The updater expects a JSON manifest served from a laptop, local network server,
USB path, or HTTPS endpoint. The app downloads the listed installer/package,
verifies its SHA-256 hash, then launches it outside the running process.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ProgressCallback = Callable[[int, int], None]


class UpdateError(RuntimeError):
    """Raised when update metadata or package handling fails."""


@dataclass
class UpdateInfo:
    latest_version: str
    download_url: str
    sha256: str
    notes: str = ""
    mandatory: bool = False
    filename: str = ""
    installer_args: list[str] | None = None
    install_mode: str = "run_installer"


def parse_version(value: str) -> tuple:
    """Return a sortable version tuple for simple semver-like strings."""
    parts = re.findall(r"\d+|[A-Za-z]+", value or "")
    parsed = []
    for part in parts:
        if part.isdigit():
            parsed.append((0, int(part)))
        else:
            parsed.append((1, part.lower()))
    return tuple(parsed)


def is_newer_version(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def _read_text(source: str, timeout: int = 10) -> str:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("http", "https"):
        req = urllib.request.Request(source, headers={"User-Agent": "SkyForge-GCS-Updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    if parsed.scheme == "file":
        return Path(urllib.request.url2pathname(parsed.path)).read_text(encoding="utf-8")
    return Path(source).read_text(encoding="utf-8")


def load_manifest(source: str, timeout: int = 10) -> UpdateInfo:
    if not source:
        raise UpdateError("Update source is empty.")
    try:
        data = json.loads(_read_text(source, timeout=timeout))
    except Exception as exc:
        raise UpdateError(f"Could not read update manifest: {exc}") from exc

    latest = str(data.get("latest_version") or data.get("version") or "").strip()
    download_url = str(data.get("download_url") or data.get("url") or "").strip()
    sha256 = str(data.get("sha256") or "").strip().lower()
    if not latest:
        raise UpdateError("Manifest is missing latest_version.")
    if not download_url:
        raise UpdateError("Manifest is missing download_url.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise UpdateError("Manifest is missing a valid sha256 hash.")

    source_parsed = urllib.parse.urlparse(source)
    download_parsed = urllib.parse.urlparse(download_url)
    if not download_parsed.scheme:
        if source_parsed.scheme in ("http", "https"):
            download_url = urllib.parse.urljoin(source, download_url)
        elif source_parsed.scheme == "file":
            source_path = Path(urllib.request.url2pathname(source_parsed.path))
            download_url = str(source_path.parent / download_url)
        else:
            download_url = str(Path(source).parent / download_url)
    installer_args = data.get("installer_args")
    if isinstance(installer_args, str):
        installer_args = [installer_args]
    elif installer_args is not None and not isinstance(installer_args, list):
        installer_args = None

    return UpdateInfo(
        latest_version=latest,
        download_url=download_url,
        sha256=sha256,
        notes=str(data.get("notes") or ""),
        mandatory=bool(data.get("mandatory", False)),
        filename=str(data.get("filename") or ""),
        installer_args=[str(x) for x in installer_args] if installer_args else None,
        install_mode=str(data.get("install_mode") or "run_installer"),
    )


def _filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = os.path.basename(urllib.parse.unquote(parsed.path))
    return name or "SkyForge_Update.exe"


def download_update(info: UpdateInfo, destination_dir: str | Path,
                    progress: ProgressCallback | None = None) -> Path:
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    filename = info.filename or _filename_from_url(info.download_url)
    final_path = destination_dir / filename
    temp_path = final_path.with_suffix(final_path.suffix + ".part")

    parsed = urllib.parse.urlparse(info.download_url)
    try:
        if parsed.scheme in ("http", "https"):
            req = urllib.request.Request(info.download_url, headers={"User-Agent": "SkyForge-GCS-Updater"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(temp_path, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        elif parsed.scheme == "file":
            src = Path(urllib.request.url2pathname(parsed.path))
            shutil.copyfile(src, temp_path)
            if progress:
                progress(temp_path.stat().st_size, temp_path.stat().st_size)
        else:
            src = Path(info.download_url)
            shutil.copyfile(src, temp_path)
            if progress:
                progress(temp_path.stat().st_size, temp_path.stat().st_size)
    except Exception as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise UpdateError(f"Could not download update package: {exc}") from exc

    digest = sha256_file(temp_path)
    if digest.lower() != info.sha256.lower():
        temp_path.unlink(missing_ok=True)
        raise UpdateError("Downloaded update failed SHA-256 verification.")

    temp_path.replace(final_path)
    return final_path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def launch_installer(path: str | Path, args: list[str] | None = None) -> None:
    path = Path(path)
    args = args or []
    suffix = path.suffix.lower()
    if suffix in (".exe", ".msi", ".bat", ".cmd"):
        subprocess.Popen([str(path), *args], close_fds=True)
        return
    if suffix == ".ps1":
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(path), *args],
            close_fds=True,
        )
        return
    os.startfile(str(path))


def launch_update_package(path: str | Path, args: list[str] | None = None,
                          install_mode: str = "run_installer",
                          current_exe: str | Path | None = None) -> None:
    """Launch an installer, or replace the current portable EXE after exit."""
    path = Path(path)
    if install_mode != "replace_exe":
        launch_installer(path, args=args)
        return

    if not current_exe:
        raise UpdateError("replace_exe mode requires the current executable path.")
    current_exe = Path(current_exe)
    if current_exe.suffix.lower() != ".exe":
        raise UpdateError("replace_exe mode is only supported for Windows EXE builds.")

    script = path.parent / "apply_skyforge_update.bat"
    script.write_text(
        "@echo off\n"
        "setlocal\n"
        "echo Applying SkyForge GCS update...\n"
        "timeout /t 2 /nobreak >nul\n"
        f'copy /Y "{path}" "{current_exe}"\n'
        "if errorlevel 1 (\n"
        "  echo Update failed. Close SkyForge GCS and run this update again.\n"
        "  pause\n"
        "  exit /b 1\n"
        ")\n"
        f'start "" "{current_exe}"\n'
        "del \"%~f0\"\n",
        encoding="utf-8",
    )
    subprocess.Popen([str(script)], close_fds=True)


def create_manifest(package_path: str | Path, latest_version: str, base_url: str = "",
                    notes: str = "", mandatory: bool = False,
                    installer_args: list[str] | None = None) -> dict:
    package_path = Path(package_path)
    download_url = package_path.name
    if base_url:
        download_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", package_path.name)
    return {
        "latest_version": latest_version,
        "download_url": download_url,
        "sha256": sha256_file(package_path),
        "filename": package_path.name,
        "mandatory": mandatory,
        "notes": notes,
        "installer_args": installer_args or [],
        "install_mode": "run_installer",
    }
