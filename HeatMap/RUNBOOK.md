# SkyWatch — Live RTSP Stream Runbook

Complete step-by-step guide to run SkyWatch with a live drone RTSP stream
(`rtsp://localhost:8554/mystream`) using MediaMTX and FFmpeg.

> **One-time setup** (Steps 1–2) only needs to be done once.  
> **Every run** (Terminals 1–5 below) must be repeated each time you start the project.

---

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- [MediaMTX](https://github.com/bluenviron/mediamtx/releases) — RTSP server
- [FFmpeg](https://ffmpeg.org/download.html) — stream publisher (added to PATH)
- A drone video file at `SkyWatch/media/videos/droneVid.mp4`
  *(or any `.mp4` you want to stream)*

---

## One-Time Setup

### Step 1 — Python environment

Backend and CV pipeline share one virtual environment, built from the project-root `requirements.txt`. Open a terminal in the `SkyWatch/` root:

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

> This downloads PyTorch (~800 MB). Allow 5–10 minutes on first run. No database setup needed — SkyWatch uses a single local SQLite file created automatically on backend startup.

### Step 2 — Frontend Node modules

Open another terminal in `SkyWatch/`:

```powershell
cd frontend
npm install
```

---

## Every Run (4 terminals required)

### Terminal 1 — MediaMTX RTSP Server

Download `mediamtx_*.zip` from https://github.com/bluenviron/mediamtx/releases,
extract it somewhere, and run:

```powershell
# From wherever you extracted MediaMTX:
.\mediamtx.exe
```

Expected output:
```
INF MediaMTX v1.x.x
INF [RTSP] listener opened on :8554
INF [HLS]  listener opened on :8888
INF [WebRTC] listener opened on :8889
```

> **HLS is enabled by default.** MediaMTX automatically re-broadcasts every
> RTSP stream as an HLS playlist at `http://localhost:8888/<stream-name>/index.m3u8`.
> The SkyWatch dashboard now uses this HLS URL to **play the live video directly in
> the browser** (no more placeholder). No extra MediaMTX configuration is needed.

Leave this terminal open.

---

### Terminal 2 — FFmpeg Stream Publisher

This pushes your local video file as a live RTSP stream into MediaMTX.

```powershell
ffmpeg -re -stream_loop -1 -i "C:\Users\RAGHAV JHA\Desktop\The IIT Ropars work\6th sem\DEP\dep\SkyWatch\media\videos\droneVid.mp4" -c copy -f rtsp rtsp://localhost:8554/mystream
```

| Flag | Meaning |
|---|---|
| `-re` | Read input at its native frame rate (simulates a live camera) |
| `-stream_loop -1` | Loop the video indefinitely |
| `-c copy` | Pass through without re-encoding (fast, no quality loss) |
| `-f rtsp` | Output format: RTSP |

Verify the stream is working:
```powershell
# Quick check (should print stream info then exit):
ffprobe rtsp://localhost:8554/mystream
```

Leave this terminal open.

---

### Terminal 3 — FastAPI Backend

```powershell
cd "C:\Users\RAGHAV JHA\Desktop\The IIT Ropars work\6th sem\DEP\dep\SkyWatch\backend"
..\venv\Scripts\uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected output:
```
[DB] SQLite database ready at ...\SkyWatch\backend\skywatch.db
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Verify: open http://localhost:8000/health — should return `{"status":"healthy","db_backend":"sqlite","db_path":"..."}`.

Leave this terminal open.

---

### Terminal 4 — React Frontend

```powershell
cd "C:\Users\RAGHAV JHA\Desktop\The IIT Ropars work\6th sem\DEP\dep\SkyWatch\frontend"
npm run dev
```

Expected output:
```
  VITE v7.x.x  ready in ~600 ms
  ➜  Local:   http://localhost:5173/
```

Leave this terminal open.

---

### Terminal 5 — Stream Processor (CV / SDNet)

```powershell
cd "C:\Users\RAGHAV JHA\Desktop\The IIT Ropars work\6th sem\DEP\dep\SkyWatch\cv_pipeline"
..\venv\Scripts\python stream_processor.py `
    --source rtsp://localhost:8554/mystream `
    --fps 5 `
    --drone-id DRN-RTSP-01 `
    --drone-name "MediaMTX Drone" `
    --zone "Test Zone" `
    --latitude 30.9683 `
    --longitude 76.4732 `
    --altitude 80 `
    --model sdnet `
    --device cpu
```

Expected output:
```
[StreamProcessor] Detected live URL: rtsp://localhost:8554/mystream
[StreamProcessor] Auto-reconnect enabled (max attempts: ∞)
[StreamProcessor] Target FPS: 5  Model: sdnet
[SDNet] Loading model on cpu...
[SDNet] Model loaded successfully.
[StreamProcessor] Stream opened successfully.
Frame 1: Headcount 24.8 → 200
Frame 2: Headcount 25.1 → 200
...
```

> `→ 200` means each frame's density data was accepted by the backend.

---

## View the Dashboard

Open **http://localhost:5173** in your browser.

| What you see | Meaning |
|---|---|
| Drone card `DRN-RTSP-01` showing `active` | Stream processor is live |
| Heatmap pulsing on the map near IIT Ropar | Crowd density data flowing |
| "Live Stream Active" badge in detail panel | RTSP URL detected (can't be played in browser — use VLC to preview) |
| Headcount number updating in real time | SDNet is counting people per frame |

---

## Changing the Stream Source

To point at a **real drone camera** instead of a looped file, just change `--source`:

```powershell
# DJI / Parrot via RTSP
..\venv\Scripts\python stream_processor.py --source rtsp://192.168.1.10:554/live --fps 5 ...

# HTTP MJPEG (GCS software, IP cameras)
..\venv\Scripts\python stream_processor.py --source http://192.168.1.20:8080/video --fps 5 ...
```

For real drone feeds, omit Step 2 (FFmpeg publisher) — the drone's GCS/app broadcasts directly.

---

## Changing the Drone Location

Edit the `--latitude`, `--longitude`, and `--altitude` flags in Terminal 5.

The heatmap on the dashboard will automatically recentre on the new coordinates.

---

## Stopping the Project

Stop in reverse order (Ctrl+C in each terminal):
1. Terminal 5 — Stream Processor
2. Terminal 4 — Frontend
3. Terminal 3 — Backend
4. Terminal 2 — FFmpeg
5. Terminal 1 — MediaMTX

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Could not open stream` (stream processor) | Ensure MediaMTX and FFmpeg are both running first |
| Stream processor keeps reconnecting | Check FFmpeg is publishing: `ffprobe rtsp://localhost:8554/mystream` |
| Dashboard shows no drones | Stream processor must be running and posting data |
| Backend port 8000 already in use | `netstat -ano \| findstr :8000` then `taskkill /PID <pid> /F` |
| Frontend port 5173 already in use | `netstat -ano \| findstr :5173` then `taskkill /PID <pid> /F` |
| SDNet model not found | Ensure `.pth` file is inside `SkyWatch/crowd_models/` |
