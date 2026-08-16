#!/usr/bin/env python
"""
Build script for SkyForge GCS - creates standalone executable and distribution package.

Usage:
    python build.py --exe        (build executable only)
    python build.py --dist       (build full distribution package)
    python build.py --clean      (clean build artifacts)
    python build.py --all        (build exe + dist)
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
import json
import zipfile
from updater import create_manifest

# Configuration
APP_NAME = "SkyForge_GCS"
VERSION_FILE = "version.txt"
BUILD_DIR = Path("build")
DIST_DIR = Path("dist")
ARCHIVE_DIR = Path("releases")

def get_version():
    """Read version from version.txt."""
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip()
    except Exception:
        return "0.1.0"

def clean_build():
    """Remove build artifacts."""
    print("[*] Cleaning build artifacts...")
    for d in [BUILD_DIR, DIST_DIR, Path("build"), Path(".egg-info")]:
        if d.exists():
            shutil.rmtree(d)
            print(f"   Removed: {d}")
    
    # Remove __pycache__ directories
    for pycache in Path(".").rglob("__pycache__"):
        shutil.rmtree(pycache)
        print(f"   Removed: {pycache}")
    
    print("✓ Clean complete")

def build_executable():
    """Build standalone executable using PyInstaller."""
    print("\n[BUILD] Building executable with PyInstaller...")
    
    # Check if PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("[ERROR] PyInstaller not installed. Install with:")
        print("   pip install pyinstaller")
        return False
    
    # Run PyInstaller
    spec_file = "skyforge_gcs.spec"
    cmd = [sys.executable, "-m", "PyInstaller", spec_file, "--clean"]
    
    print(f"   Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode == 0:
        exe_path = DIST_DIR / f"{APP_NAME}.exe"
        if exe_path.exists():
            print(f"[OK] Executable created: {exe_path}")
            print(f"   Size: {exe_path.stat().st_size / 1024 / 1024:.1f} MB")
            return True
        else:
            print(f"[ERROR] Executable not found at {exe_path}")
            return False
    else:
        print("[ERROR] PyInstaller build failed")
        return False

def create_distribution_package():
    """Create a distributable package with all files."""
    print("\n[PACKAGE] Creating distribution package...")
    
    version = get_version()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_name = f"SkyForge_GCS_v{version}_{timestamp}"
    package_dir = ARCHIVE_DIR / package_name
    
    # Create release directory
    ARCHIVE_DIR.mkdir(exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy executable
    exe_src = DIST_DIR / f"{APP_NAME}.exe"
    exe_dst = None
    if exe_src.exists():
        exe_dst = package_dir / f"{APP_NAME}.exe"
        shutil.copy(exe_src, exe_dst)
        print(f"   [+] Copied executable")
    else:
        print(f"   [!] Executable not found at {exe_src}")
    
    # Copy documentation
    docs = ["README.md", "QUICKSTART.md", "IMPLEMENTATION.md"]
    for doc in docs:
        if Path(doc).exists():
            shutil.copy(doc, package_dir)
            print(f"   [+] Copied {doc}")
    
    # Copy configuration template
    if Path("skyforge_config.json").exists():
        shutil.copy("skyforge_config.json", package_dir)
        print(f"   [+] Copied configuration template")
    
    # Create run script
    run_script = package_dir / "run.bat"
    with open(run_script, "w") as f:
        f.write(f"""@echo off
REM SkyForge GCS Launcher
REM Run the application with optional arguments

echo Launching SkyForge GCS v{version}...
{APP_NAME}.exe %*
pause
""")
    print(f"   [+] Created run.bat launcher")

    # Create a local update server launcher for field updates from a laptop.
    update_server_script = package_dir / "START_UPDATE_SERVER.bat"
    with open(update_server_script, "w") as f:
        f.write("""@echo off
echo SkyForge GCS update server
echo.
echo 1. Keep this window open.
echo 2. On the field laptop, set the app update source to:
echo    http://YOUR-LAPTOP-IP:8000/update_manifest.json
echo.
python -m http.server 8000
pause
""")
    print(f"   [+] Created START_UPDATE_SERVER.bat")
    
    # Create installation instructions
    install_guide = package_dir / "INSTALL.md"
    with open(install_guide, "w") as f:
        f.write(f"""# SkyForge GCS v{version} - Installation Guide

## Quick Start

1. **Extract** this folder to any location on your laptop
2. **Run** the application:
   - Windows: Double-click `run.bat` or `{APP_NAME}.exe`
   - Command line: `.\\{APP_NAME}.exe`

## First Launch

- **No dependencies needed!** Everything is bundled inside the executable
- On first launch, the app will:
  - Create `data/` folder beside `{APP_NAME}.exe` for mission archives
  - Create `logs/` folder beside `{APP_NAME}.exe` for diagnostics
  - Generate default config at `skyforge_config.json`

## Field Updates From Your Laptop

1. On your laptop, open this release folder
2. Double-click `START_UPDATE_SERVER.bat`
3. Note your laptop IP address on the same network as the field machine
4. In SkyForge GCS on the field machine, open:
   - Help -> Set Update Source
   - Enter `http://YOUR-LAPTOP-IP:8000/update_manifest.json`
5. Open Help -> Check for Updates
6. Confirm the update and let the app restart

## Operating Modes

### Simulation (Demo Mode - No Hardware)
1. Launch the app
2. Click "Simulation" mode
3. Click START
4. Select a folder with JPEG images
5. Watch orthomosaic render in real-time

### MAVLink Live (With Autopilot)
1. Connect autopilot (Pixhawk, Cube, etc.) to laptop via USB/serial
2. Power on drone and wait for GPS lock
3. Launch app -> Select "MAVLink Live" mode
4. Click START
5. Autopilot telemetry + camera feed will stream
6. Fly mission and watch map update in real-time

### File Upload (Post-Mission Analysis)
1. Launch app -> Select "File Upload" mode
2. Click START
3. Select a folder of JPEG images
4. Orthomosaic will generate from the uploaded images

## Configuration

Edit `skyforge_config.json` to customize:
- MAVLink endpoint (default: auto-detect)
- Camera source (default: 0 = webcam)
- Map resolution (default: 0.5 m/pixel)
- Processing mode (GPS-only or pose-graph optimized)

## Mission Export

After mapping:
- **Quick Export**: Saves current map as PNG
- **Mission Export**: Creates full archive with:
  - Orthomosaic map (PNG)
  - All input frames (JPEGs)
  - Telemetry data (CSV + JSON)
  - Processing summary (JSON)
  - Mission report (PDF, optional)

All exports are saved to the `data/` folder beside `{APP_NAME}.exe` with timestamp.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| App won't start | Right-click -> Run as Administrator |
| No camera appears | Try Simulation mode first; use "0" or "none" |
| MAVLink won't connect | Ensure autopilot is powered + GPS locked |
| Map renders too slowly | Lower resolution in config (0.1 vs 0.5 m/px) |
| Out of memory | Reduce map resolution or process fewer frames |

## System Requirements

- **OS**: Windows 7 SP1 or later (64-bit)
- **CPU**: Intel/AMD dual-core 2 GHz or better
- **RAM**: 2-4 GB minimum (4-8 GB recommended)
- **Disk**: 500 MB free space
- **USB**: Optional (for autopilot or HDMI camera)

## Support

For issues or feature requests:
1. Check `logs/` folder for diagnostics
2. Review `README.md` and `QUICKSTART.md`
3. Consult `IMPLEMENTATION.md` for technical details

---

**Build Date**: {timestamp}
**Version**: {version}
**Status**: Ready for field deployment [OK]
""")
    print(f"   [+] Created INSTALL.md")
    
    # Create metadata
    metadata = {
        "name": APP_NAME,
        "version": version,
        "build_date": timestamp,
        "includes": ["executable", "documentation", "configuration"],
    }
    with open(package_dir / "manifest.json", "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"   [+] Created manifest.json")

    # Create in-app updater manifest. Serve this package_dir over HTTP, or copy
    # the manifest and executable to any web server/USB path.
    if exe_dst and exe_dst.exists():
        update_manifest = create_manifest(
            exe_dst,
            latest_version=version,
            notes="SkyForge GCS field update.",
        )
        update_manifest["install_mode"] = "replace_exe"
        with open(package_dir / "update_manifest.json", "w") as f:
            json.dump(update_manifest, f, indent=2)
        print(f"   [+] Created update_manifest.json")
    
    # Create ZIP archive
    zip_path = ARCHIVE_DIR / f"{package_name}.zip"
    print(f"\n   [*] Creating ZIP archive: {zip_path}")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in package_dir.rglob("*"):
            if item.is_file():
                arcname = item.relative_to(ARCHIVE_DIR)
                zf.write(item, arcname)
    
    zip_size = zip_path.stat().st_size / 1024 / 1024
    print(f"[OK] Distribution package created: {zip_path}")
    print(f"   Size: {zip_size:.1f} MB")
    print(f"   Directory: {package_dir}")
    
    return True

def main():
    """Main build orchestrator."""
    parser = argparse.ArgumentParser(
        description="Build SkyForge GCS standalone executable and distribution package"
    )
    parser.add_argument(
        "--exe",
        action="store_true",
        help="Build executable only"
    )
    parser.add_argument(
        "--dist",
        action="store_true",
        help="Create distribution package"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean build artifacts"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Build exe + dist (full build)"
    )
    
    args = parser.parse_args()
    
    # Default: build all
    if not any([args.exe, args.dist, args.clean]):
        args.all = True
    
    print(f"\n{'='*60}")
    print(f"  SkyForge GCS Build System")
    print(f"  Version: {get_version()}")
    print(f"  Build started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    if args.clean:
        clean_build()
    
    if args.exe or args.all:
        success_exe = build_executable()
        if not success_exe and args.all:
            print("[!] Executable build failed; skipping distribution package")
            return 1
    
    if args.dist or (args.all and (args.exe or not args.exe)):
        success_dist = create_distribution_package()
        if not success_dist:
            return 1
    
    print(f"\n{'='*60}")
    print(f"  [OK] Build complete!")
    print(f"{'='*60}\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
