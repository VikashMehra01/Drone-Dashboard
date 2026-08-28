# SkyWatch – Real-time Drone Surveillance Portal

<div align="center">
  <h3>Real-time crowd-density monitoring using drone video streams, CV-based crowd counting, FastAPI APIs, and a modern React + Leaflet dashboard.</h3>
</div>

---

## 📖 Overview

**SkyWatch** ingests live (or simulated) drone video streams, runs a deep-learning crowd-counting model on each frame, and streams the resulting headcount/density data to a React dashboard that plots drones on a live map, renders a crowd-density heatmap, plays the video feed inline, and fires Telegram alerts when a zone gets too crowded.

### ✨ Key Features

- **Multi-Protocol Video Ingestion**: RTSP, RTMP, HTTP MJPEG, or simulated streams from local `.mp4` files.
- **AI-Powered Crowd Density**: Deep-learning density-map estimation (**SDNet**, from the vendored [`crowd_models`](crowd_models) research repo) or classic **YOLOv8** person detection (COCO-pretrained, or a VisDrone-pretrained variant tuned for aerial/drone-camera footage), both running via PyTorch. The available models are admin-configurable in one place ([`stream_config.py`](cv_pipeline/stream_config.py)'s `MODEL_PRESETS`) and exposed to the dashboard via `GET /api/auth/models`.
- **Dynamic Heatmaps & Telemetry**: Live drone coordinates, altitude, battery, and geospatial crowd heatmaps rendered on a Leaflet map.
- **Zero-Setup Backend**: FastAPI backed by a single local SQLite file — no external database server or Docker container required.
- **Telegram Alert Integration**: Automatic push notifications when a drone's sustained headcount crosses a configurable threshold.
- **Admin Console**: Launch/stop/resume CV stream processors and manage users directly from the dashboard.
- **Sleek React Dashboard**: Vite + React + MUI + Tailwind, with live HLS video playback and dark/light mode.

---

## 🏗 System Architecture

SkyWatch is three cooperating processes plus a local database file, glued together over HTTP:

```
Video Source                  cv_pipeline/                        backend/ (FastAPI)
(RTSP / RTMP / HTTP    ─cv2──▶ stream_processor.py           ─POST─▶ POST /api/density/update
 or local .mp4 file)    read    └─ detection.py                json  GET  /api/drones/*
                                    ├─ SDNetDetector (SDNet)          POST /api/alerts/broadcast
                                    └─ YOLODetector (YOLOv8)          /api/auth/*  (JWT)
                                                                             │
                                                                             │ SQL (raw)
                                                                             ▼
                                                                  SQLite (backend/skywatch.db)
                                                                             │
                                                                             │ REST, polled every 1s
                                                                             ▼
                                                                  frontend/ (React + Vite)
                                                                  Dashboard · MapView (Leaflet heatmap)
                                                                  DroneFeed (HLS/MP4) · Analytics · AdminPanel
```

### Components

1. **`cv_pipeline/`** — the CV worker. `stream_processor.py` opens a video source with OpenCV, runs every frame through a pluggable `PersonDetector` (SDNet or YOLO), and HTTP-POSTs `{headcount, points_count, timestamp, drone_id, lat/lon/alt, zone, loop_video}` to the backend. One process per drone; the backend admin API spawns these as detached subprocesses (`--drone-id`, `--source`, `--model`, `--device`, …). PyTorch/OpenCV are capped to a small CPU thread pool per process (`--threads`, default 2 — see `DEFAULT_NUM_THREADS` in `stream_config.py`), since left uncapped a single inference call otherwise claims every logical core on the machine.

2. **`backend/`** — the API + state layer (FastAPI). It:
   - Accepts density updates from every running `stream_processor.py` and keeps an in-memory map of active streams (`active_streams`), keyed by source URL.
   - Persists a sampled subset of points to `density_records` / `drones` tables in a local SQLite file (`backend/skywatch.db`), via `app/db.py`.
   - Serves `/api/drones` (merges live streams + saved-but-stopped configs + idle drones), `/api/density/current` and `/api/density/history` (bucketed time-series for the Analytics page), `/api/alerts/broadcast` (Telegram), `/api/auth/*` (JWT login + admin user/drone management), and `/api/auth/models` (the admin-configurable detection-model list, sourced from `cv_pipeline/stream_config.py`).
   - `/api/auth/drones/launch|stop|resume` lets an admin manage `stream_processor.py` subprocesses from the UI — it shells out to spawn/kill the Python process and tracks liveness via the `pid`/`status` columns on the persisted `drone_configs` table (checked with `psutil` through `drone_registry.py`), which is the single source of truth — no PID files or separate in-memory registry to drift out of sync.
   - Serves local demo videos as static files under `/videos` (from `media/videos/`).

3. **`frontend/`** — the dashboard (React + Vite). A single shared poll of `/api/drones/` and `/api/density/current` every 1s (`DronesContext`) feeds every component that needs live fleet data — Sidebar, Dashboard, MapView, DensityStats, DroneFeed — instead of each running its own independent interval against the same endpoints. It plots drones on a Leaflet map with a heatmap overlay (`leaflet.heat`), plays each drone's feed (HLS via `hls.js` for live RTSP-derived streams, native `<video>` for local files), reverse-geocodes drone coordinates to Indian state/district via Nominatim for filtering, and raises in-app + Telegram alerts when a drone's headcount stays above its configured threshold for multiple consecutive frames (`NotificationContext`).

4. **`crowd_models/`** — a vendored copy of the official implementation of *"Video Individual Counting for Moving Drones"* (ICCV 2025 Highlight), providing the **SDNet** model architecture and pretrained checkpoint that `sdnet_detector.py` loads for inference. See [Libraries & Attribution](#-libraries--tech-stack) below.

5. **`video-stream/`** — an unfinished RTSP-simulator; its script is a stub (see [Repo cleanup](#-repo-cleanup)). In practice, live-stream simulation is done manually with MediaMTX + FFmpeg per [RUNBOOK.md](RUNBOOK.md).

### End-to-end data flow (one frame)

1. `stream_processor.py` reads a frame via `cv2.VideoCapture` (local file loop, or auto-reconnecting live URL).
2. The frame goes to `PersonDetector.detect_people()`, which delegates to:
   - **SDNet** (`sdnet_detector.py`): resizes/normalizes the frame, pairs it with the previous frame (SDNet is a *temporal* shared-density model), runs `Video_Counter.test_forward()`, sums the predicted density map for the headcount, and extracts head positions via local-maxima peak-finding on the density map.
   - **YOLO** (`yolo_detector.py`): runs Ultralytics YOLOv8n, filters to the model preset's configured `person_classes` (COCO's single `person` class, or VisDrone's `pedestrian` + `people` classes for the `yolo-visdrone` preset), and returns box-center points.
3. `stream_processor.py` posts `{headcount, points_count, timestamp, drone_id, lat, lon, alt, zone, loop_video}` to `POST /api/density/update`.
4. The backend updates `active_streams` in memory (used for “live” polling) and, at most once every `HISTORY_SAMPLE_SECONDS`, persists a point to `density_records` for the Analytics history endpoint.
5. `DronesContext` polls `/api/drones/` (fleet list + coordinates) and `/api/density/current` (live headcount per drone) every 1s and shares the result with every subscribed component, which update the Leaflet heatmap/markers; each drone's rolling headcount also feeds `NotificationContext`, which raises a toast + `/api/alerts/broadcast` → Telegram call if the threshold is sustained.

### How video reaches the models (local file vs. live stream)

There is **one code path** for both cases — `cv2.VideoCapture` plus a `while` loop
that pulls one frame at a time and hands it straight to the detector
(`cv_pipeline/stream_processor.py` → `process_stream()`). The model never sees a
"stream"; it only ever receives a single decoded `numpy` BGR image per call to
`PersonDetector.detect_people(frame)`. What changes between a file and a live URL
is **only what the capture handle is bound to** and **how the loop reacts to the
end of data**.

```
LOCAL FILE                                   LIVE STREAM (rtsp:// / rtmp:// / http://)
──────────                                   ─────────────────────────────────────────
cv2.VideoCapture("…/droneVid.mp4")           cv2.VideoCapture("rtsp://host:554/live")
  └─ OpenCV opens the file on disk             └─ OpenCV hands the URL to its bundled
                                                 FFmpeg (libavformat/libavcodec), which:
                                                 1. does the protocol handshake
                                                    (RTSP DESCRIBE/SETUP/PLAY, RTMP
                                                    handshake, or HTTP GET)
                                                 2. runs a background thread reading
                                                    encoded packets (RTP / FLV / …)
                                                    off the TCP/UDP socket
                                                 3. decodes them (H.264 → raw frames)
                                                 4. keeps decoded frames in a small
                                                    internal queue
        │                                                    │
        ▼                                                    ▼
   ret, frame = cap.read()   ← identical call; returns (True, <H×W×3 BGR ndarray>) either way
        │
        ▼
   detector.detect_people(frame)   ← frame is downscaled to width 480
                                     (DETECTION_MAX_WIDTH) inside the detector, then inferred
        │
        ▼
   POST /api/density/update   → then sleep to pace the loop at --fps (default 5)
```

So, to answer the common question directly: **yes — the worker holds the live
connection open and continuously pulls frames from it in a loop, throttled to
`--fps`.** It is a *pull* loop, not a push: nothing is rendered to a screen and
nothing is written to disk. The stream keeps flowing on the wire whether we read
or not; each `cap.read()` just takes the next frame FFmpeg has decoded.

**The differences, all in loop *control* (not in how a frame reaches the model):**

| Aspect | Local file | Live stream |
|---|---|---|
| `cap.read()` returns `False` | end of file → rewind (`--loop true`, the default) or stop | connection dropped → `cap.release()`, then the **outer `while` loop** re-opens the source with exponential backoff (`RECONNECT_DELAY_SECONDS` 3s → 30s cap; `--max-reconnect-attempts 0` = retry forever) |
| Looping | `loop_video` honoured | forced to `False` — a live feed has no "start" to seek to |
| FFmpeg options | none | `_apply_ffmpeg_capture_options()` sets `OPENCV_FFMPEG_CAPTURE_OPTIONS` before opening — `rtsp_transport;tcp` for RTSP, `rtmp_live;live\|fflags;nobuffer` for RTMP (override via the env var) |
| Frame rate vs. `--fps` | file is decoded no faster than the loop consumes it, so every frame is seen (subsampled only by the `--fps` sleep) | the camera/publisher produces at its own rate (often 25–30 fps). We read one frame per iteration then `sleep(1/fps - elapsed)`. Between our reads FFmpeg keeps decoding into its queue, so with a small queue we effectively **sample the newest frames and skip the rest**. If inference is slower than `1/fps`, no sleep happens and the worker can drift behind the live edge (latency creep); `fflags;nobuffer` / `rtmp_live;live` keep that bounded. A stricter cap would be `cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)` or a grab-drain loop — not currently done. |
| Temporal model (SDNet) | consecutive file frames are naturally contiguous | SDNet pairs each frame with the previous one; right after a reconnect the "previous frame" is stale, so the first couple of density maps are noisy until a steady cadence re-establishes |

The frame handed to `detect_people()` is always the **full source resolution**
that came out of `cap.read()`; each detector then resizes it to
`DETECTION_MAX_WIDTH` (480 px wide, aspect preserved) so per-frame CPU cost and
the effective input size are identical across models and across file/live
sources.

---

## 🧰 Libraries & Tech Stack

| Layer | Stack |
|---|---|
| **Frontend** | React 19, Vite 7, React Router 7, MUI 9 + Emotion, Tailwind CSS 4, `react-leaflet` 5 / `leaflet` + `leaflet.heat` (map & heatmap), `hls.js` (live HLS playback), `recharts` (Analytics charts), `lucide-react` (icons) |
| **Backend API** | FastAPI 0.109, Uvicorn, Pydantic, stdlib `sqlite3`, PyJWT + `bcrypt` (auth), `psutil` (portable process control), `python-dotenv` |
| **CV / stream worker** | OpenCV (`cv2`), PyTorch + TorchVision, Ultralytics (YOLOv8), `requests` (posts to backend) |
| **Crowd-counting model** | **SDNet** (Shared Density-map-guided Network) — ViT/ResNet/VGG-FPN backbones, cross-attention temporal fusion — from the vendored [`crowd_models`](crowd_models) repo. `timm`, `easydict`, SciPy, Pandas, Pillow support it. |
| **Database** | SQLite — a single local file (`backend/skywatch.db`), created and migrated automatically on backend startup. No server process, no Docker. |
| **Infra** | MediaMTX + FFmpeg (manual RTSP/HLS relay for local demos) — everything else runs as a plain local process (`uvicorn`, `npm run dev`, `python stream_processor.py`) |

**Attribution:** `crowd_models/` is the official PyTorch implementation accompanying *"Video Individual Counting for Moving Drones"* (ICCV 2025 Highlight, [arXiv:2503.10701](https://arxiv.org/abs/2503.10701)). It's included wholesale for its SDNet model code and a pretrained `.pth` checkpoint; only `config.py`, `model/`, and `misc/` (the modules imported transitively by `model/VIC.py`) are used at inference time by `cv_pipeline/sdnet_detector.py`. `datasets/`, `train.py`, `test.py`, and the evaluation/metrics utilities in `misc/` are training/reproduction code for the original paper and are not exercised by the live app.

---

## 🚀 Getting Started

### Prerequisites

To run SkyWatch locally, you will need:
- **Python 3.10 (strictly required)**
- **Node.js 18+** and **npm**
- *(Optional but recommended)* **MediaMTX** and **FFmpeg** for simulating live RTSP streams.

No database server or Docker is required — SkyWatch uses a single local SQLite file, created automatically the first time the backend starts.

> **Why Python 3.10?** In the AI/ML ecosystem, Python 3.10 is the universally supported standard. Newer versions of Python (like 3.12 or 3.14) lack stable pre-compiled C++ binaries ("wheels") for core dependencies like `numpy==1.26.3`, `torch`, and `opencv-python`. Sticking strictly to 3.10 guarantees that all deep learning libraries will install instantly without failing on complex C++ compiler errors.

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/SkyWatch.git
cd SkyWatch
```

---

### 2. Configure Environment Variables

Copy the example environment file and update it with your actual secrets if required. For local development, the defaults usually suffice.

```bash
cp .env.example .env
```

---

### 3. Create the Python Environment

Backend and CV pipeline share a single virtual environment at the project root, built from the consolidated `requirements.txt` (merged from `backend/`, `cv_pipeline/`, and `crowd_models/` — see that file's header for details on version pins). First install downloads PyTorch (~800 MB) — allow 5–10 minutes.

**Linux / macOS:**
```bash
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
py -3.10 -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

> Prefer isolated environments instead? `backend/requirements.txt` and `cv_pipeline/requirements.txt` are still there and installable on their own.

---

### 4. Start the FastAPI Backend

Open a **new terminal** window. The first run creates `backend/skywatch.db` automatically — nothing else to configure.

**Linux / macOS:**
```bash
cd backend
source ../venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Windows (PowerShell):**
```powershell
cd backend
..\venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
*The API will be available at `http://localhost:8000`. Check `http://localhost:8000/health` to confirm it is running.*

---

### 5. Start the React Frontend

Open a **new terminal** window:

```bash
cd frontend
npm install
npm run dev
```
*The dashboard will be available at `http://localhost:5173`. Log in with `admin` / `admin`.*

---

### 6. Start a Drone Feed

The easiest way: log into the dashboard as admin and use **Admin → Add Drone** — it launches `stream_processor.py` for you (point `Stream Source` at one of the sample files in `media/videos/`, or a live RTSP/RTMP/HTTP URL).

To run one manually instead (useful for watching its raw log output), open a **new terminal**:

```bash
cd cv_pipeline
source ../venv/bin/activate      # Windows: ..\venv\Scripts\activate
python stream_processor.py \
  --source "../media/videos/droneVid.mp4" \
  --fps 5 \
  --drone-id DRN-LIVE-01 \
  --drone-name "DJI Mavic 3" \
  --latitude 30.9683 \
  --longitude 76.4732 \
  --altitude 80
```

> **Note:** To run multiple drones simultaneously (whether via the UI or manually), just use a different `--drone-id`, coordinates, and `--source` for each.

---

## 📡 Live Stream Simulation Guide (Advanced)

If you want to simulate a true live streaming environment locally (so the frontend plays the video directly in the browser rather than a placeholder), refer to our detailed **[RUNBOOK.md](RUNBOOK.md)**.

The runbook provides step-by-step instructions on how to:
1. Spin up a local **MediaMTX** RTSP server.
2. Use **FFmpeg** to continuously push a local `.mp4` file to the RTSP server.
3. Configure the dashboard to pick up the auto-generated HLS stream for seamless browser playback.

---

## 🛠 Project Layout

```text
SkyWatch/
├── backend/          # FastAPI application & API routers
├── frontend/         # Vite + React Dashboard (Tailwind + MUI + Leaflet)
├── cv_pipeline/      # PyTorch CV pipeline & stream processing daemon
├── crowd_models/     # Crowd-counting model implementations (currently: vendored SDNet, ICCV 2025)
├── media/            # Sample video files for local simulation
├── video-stream/     # Unfinished RTSP-simulator Docker service (see below)
├── .env.example      # Environment variables template
├── README.md         # You are here
└── RUNBOOK.md        # Advanced guide for simulating live RTSP streams
```

---

## 🗑 Repo cleanup

A read-through of the codebase turned up files that were superseded, stubbed out, or leftover from earlier iterations. The dead ones have been removed; a couple of non-functional-but-intentional pieces were kept on request and are just flagged below.

### Removed

- **Backend**: `app/models/density.py` + `drone.py` (unused SQLAlchemy models — the app talks to the DB via raw SQL in `app/db.py` instead), `app/services/density_calculator.py` (all-`TODO` stub, never imported), `app/services/video_processor.py` (never imported — `cv_pipeline/stream_processor.py` does that job), `package-lock.json` (empty npm lockfile in a pure-Python backend).
- **Root**: `clean.sh`, `filter.sh`, `run_filter.py` (one-off `git filter-branch` scripts used to scrub a leaked Telegram bot token out of history), `package-lock.json` (empty, orphaned), `sync_data.ps1` + `frontend/public/headcount_data.csv` (synced a CSV that was never read by the frontend, from a pipeline that no longer exists).
- **`cv_pipeline/`**: `main.py`, `heatmap.py`, `transformation.py`, `data_ingestion.py` and their sample artifacts (`dronetest.mp4`, `output_heatmap.mp4`, etc.) — the offline batch pipeline, never called by the live app. `drone_DRN-*.log` / `.json` — machine-generated per-drone runtime logs, now covered by `.gitignore` so they won't be committed again.
- **Frontend**: `src/map.jsx` + `src/mapData.js` (prototype map, superseded by `components/MapView.jsx`), `src/data/mockData.js` (unused hard-coded drone data), `update_css.cjs` (one-off CSS patch script, not wired into any npm command), `src/assets/react.svg` (default Vite template leftover).
- **Docker & Postgres, entirely**: `docker-compose.yml`'s `frontend` service referenced a Dockerfile that never existed under `frontend/` (would fail to build); its `backend` service was buildable but never actually used (docs always ran the backend as a local `uvicorn` process) and functionally incomplete anyway — the container had no access to the sibling `cv_pipeline/`/`media/` directories the backend needs to launch drones or serve videos. `backend/Dockerfile` removed with it. Investigating further turned up that the app's PostgreSQL/PostGIS support wasn't earning its keep either — no application query anywhere used a PostGIS spatial function, so it was pure overhead requiring a Docker Postgres container for zero benefit over the already-solid SQLite fallback. Removed Postgres support entirely rather than just defaulting away from it: `app/db.py` is now a plain SQLite module (no more dual-backend abstraction or Postgres-SQL-to-SQLite translation shim), `psycopg2-binary` is gone from every `requirements.txt`, and `docker-compose.yml` / `database/init.sql` (pure Postgres DDL, no longer referenced by anything) were deleted outright. Also dropped five dead settings from `backend/app/config.py` / `.env.example`: `RTSP_URL`, `FRAME_INTERVAL`, `YOLO_MODEL`, `CONFIDENCE_THRESHOLD` (only consumer was the already-removed `video_processor.py`) and now `DATABASE_URL` too. One real bug turned up along the way and got fixed: the SQLite `users` table was missing the `created_at` column `GET /api/auth/users` queried for — would have 500'd every time on a SQLite-backed install, pre-dating this change.

### Flagged but kept (by request)

- **`video-stream/`** — meant to simulate an RTSP feed. Its only script, `simulate_feed.py`, is an unimplemented stub (`print("Video stream simulator not yet implemented.")`) — it currently does nothing, and there's no `docker-compose.yml` anymore to wire it into. Real RTSP simulation is done manually via MediaMTX + FFmpeg per `RUNBOOK.md`. Kept in case it gets finished later.
- **`crowd_models/`'s training/reproduction code** — `datasets/`, `train.py`, `test.py`, `misc/{evaluation_code,KPI_pool,get_bbox,cal_mean,dataparallel,modelsummary,nms,inflation,pos_embed,post_process,tools}.py`, and `model/{PreciseRoIPooling,MatchTool,optimal_transport_layer.py,ViT/models_mae_cross.py}`. Verified by tracing the actual import graph from `model/VIC.py`: none of this is touched at inference time (notably, `PreciseRoIPooling`'s only reference anywhere is inside a fully commented-out training method). Kept intentionally so the paper's original training/eval pipeline stays reproducible and reusable as more models get added here.
- **`backend/app/routers/density.py::get_heatmap_data`** (`GET /api/density/heatmap`) — stub endpoint, always returns `{"points": [], "timestamp": None}`; the frontend builds its heatmap client-side from `/api/density/current` instead. Left as-is since it's a single stub function, not a standalone file.

---

## 📝 License

This project is open-source and available under standard MIT guidelines. Feel free to fork, modify, and integrate into your own fleet management systems.
