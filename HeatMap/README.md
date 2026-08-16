# SkyWatch – Real-time Drone Surveillance Portal

<div align="center">
  <h3>Real-time crowd-density monitoring using drone video streams, CV-based crowd counting, FastAPI APIs, and a modern React + Leaflet dashboard.</h3>
</div>

---

## 📖 Overview

**SkyWatch** ingests live (or simulated) drone video streams, runs a deep-learning crowd-counting model on each frame, and streams the resulting headcount/density data to a React dashboard that plots drones on a live map, renders a crowd-density heatmap, plays the video feed inline, and fires Telegram alerts when a zone gets too crowded.

### ✨ Key Features

- **Multi-Protocol Video Ingestion**: RTSP, RTMP, HTTP MJPEG, or simulated streams from local `.mp4` files.
- **AI-Powered Crowd Density**: Deep-learning density-map estimation (**SDNet**, from the vendored [`crowd_models`](crowd_models) research repo) or classic **YOLOv8** person detection, both running via PyTorch.
- **Dynamic Heatmaps & Telemetry**: Live drone coordinates, altitude, battery, and geospatial crowd heatmaps rendered on a Leaflet map.
- **Resilient Backend**: FastAPI with automatic fallback to a local SQLite database when PostgreSQL is unavailable.
- **Telegram Alert Integration**: Automatic push notifications when a drone's sustained headcount crosses a configurable threshold.
- **Admin Console**: Launch/stop/resume CV stream processors and manage users directly from the dashboard.
- **Sleek React Dashboard**: Vite + React + MUI + Tailwind, with live HLS video playback and dark/light mode.

---

## 🏗 System Architecture

SkyWatch is three cooperating processes plus a database, glued together over HTTP:

```
Video Source                  cv_pipeline/                        backend/ (FastAPI)
(RTSP / RTMP / HTTP    ─cv2──▶ stream_processor.py           ─POST─▶ POST /api/density/update
 or local .mp4 file)    read    └─ detection.py                json  GET  /api/drones/*
                                    ├─ SDNetDetector (SDNet)          POST /api/alerts/broadcast
                                    └─ YOLODetector (YOLOv8)          /api/auth/*  (JWT)
                                                                             │
                                                                             │ SQL (raw)
                                                                             ▼
                                                                  PostgreSQL + PostGIS
                                                                  (falls back to a local
                                                                   SQLite file if down)
                                                                             │
                                                                             │ REST, polled every ~5s
                                                                             ▼
                                                                  frontend/ (React + Vite)
                                                                  Dashboard · MapView (Leaflet heatmap)
                                                                  DroneFeed (HLS/MP4) · Analytics · AdminPanel
```

### Components

1. **`cv_pipeline/`** — the CV worker. `stream_processor.py` opens a video source with OpenCV, runs every frame through a pluggable `PersonDetector` (SDNet or YOLO), and HTTP-POSTs `{headcount, points_count, timestamp, drone_id, lat/lon/alt, zone, loop_video}` to the backend. One process per drone; the backend admin API spawns these as detached subprocesses (`--drone-id`, `--source`, `--model`, `--device`, …).

2. **`backend/`** — the API + state layer (FastAPI). It:
   - Accepts density updates from every running `stream_processor.py` and keeps an in-memory map of active streams (`active_streams`), keyed by source URL.
   - Persists a sampled subset of points to `density_records` / `drones` tables (PostgreSQL, or SQLite fallback via `app/db.py`'s dialect-translating shim).
   - Serves `/api/drones` (merges live streams + saved-but-stopped configs + idle drones), `/api/density/current` and `/api/density/history` (bucketed time-series for the Analytics page), `/api/alerts/broadcast` (Telegram), and `/api/auth/*` (JWT login + admin user/drone management).
   - `/api/auth/drones/launch|stop|resume` lets an admin manage `stream_processor.py` subprocesses from the UI — it shells out to spawn/kill the Python process and tracks PID files + an in-memory registry (`drone_registry.py`) alongside the persisted `drone_configs` table.
   - Serves local demo videos as static files under `/videos` (from `media/videos/`).

3. **`frontend/`** — the dashboard (React + Vite). Polls `/api/drones/` and `/api/density/current` on ~5s intervals, plots drones on a Leaflet map with a heatmap overlay (`leaflet.heat`), plays each drone's feed (HLS via `hls.js` for live RTSP-derived streams, native `<video>` for local files), reverse-geocodes drone coordinates to Indian state/district via Nominatim for filtering, and raises in-app + Telegram alerts when a drone's headcount stays above its configured threshold for multiple consecutive frames (`NotificationContext`).

4. **`crowd_models/`** — a vendored copy of the official implementation of *"Video Individual Counting for Moving Drones"* (ICCV 2025 Highlight), providing the **SDNet** model architecture and pretrained checkpoint that `sdnet_detector.py` loads for inference. See [Libraries & Attribution](#-libraries--tech-stack) below.

5. **`database/`** — PostgreSQL/PostGIS schema (`init.sql`), used when running via Docker Compose.

6. **`video-stream/`** — a Docker service intended to simulate an RTSP feed from a local file; **currently a stub** (see [Files that don't contribute](#-files-that-dont-contribute-dead--unused)). In practice, live-stream simulation is done manually with MediaMTX + FFmpeg per [RUNBOOK.md](RUNBOOK.md).

### End-to-end data flow (one frame)

1. `stream_processor.py` reads a frame via `cv2.VideoCapture` (local file loop, or auto-reconnecting live URL).
2. The frame goes to `PersonDetector.detect_people()`, which delegates to:
   - **SDNet** (`sdnet_detector.py`): resizes/normalizes the frame, pairs it with the previous frame (SDNet is a *temporal* shared-density model), runs `Video_Counter.test_forward()`, sums the predicted density map for the headcount, and extracts head positions via local-maxima peak-finding on the density map.
   - **YOLO** (`yolo_detector.py`): runs Ultralytics YOLOv8n, filters to the `person` class, and returns box-center points.
3. `stream_processor.py` posts `{headcount, points_count, timestamp, drone_id, lat, lon, alt, zone, loop_video}` to `POST /api/density/update`.
4. The backend updates `active_streams` in memory (used for “live” polling) and, at most once every `HISTORY_SAMPLE_SECONDS`, persists a point to `density_records` for the Analytics history endpoint.
5. The frontend polls `/api/drones/` (fleet list + coordinates) and `/api/density/current` (live headcount per drone) every ~5s, updates the Leaflet heatmap/markers, and feeds each drone's rolling headcount into `NotificationContext`, which raises a toast + `/api/alerts/broadcast` → Telegram call if the threshold is sustained.

---

## 🧰 Libraries & Tech Stack

| Layer | Stack |
|---|---|
| **Frontend** | React 19, Vite 7, React Router 7, MUI 9 + Emotion, Tailwind CSS 4, `react-leaflet` 5 / `leaflet` + `leaflet.heat` (map & heatmap), `hls.js` (live HLS playback), `recharts` (Analytics charts), `lucide-react` (icons) |
| **Backend API** | FastAPI 0.109, Uvicorn, Pydantic, SQLAlchemy 2 (models only — see below), `psycopg2-binary` (PostgreSQL), stdlib `sqlite3` (fallback), PyJWT + `bcrypt` (auth), `python-dotenv` |
| **CV / stream worker** | OpenCV (`cv2`), PyTorch + TorchVision, Ultralytics (YOLOv8), `requests` (posts to backend) |
| **Crowd-counting model** | **SDNet** (Shared Density-map-guided Network) — ViT/ResNet/VGG-FPN backbones, cross-attention temporal fusion, Precise RoI Pooling — from the vendored [`crowd_models`](crowd_models) repo. `timm`, `easydict`, SciPy, Pandas, Pillow support it. |
| **Database** | PostgreSQL + PostGIS (production/Docker), auto-fallback to a local SQLite file (`backend/skywatch.db`) when Postgres is unreachable |
| **Infra** | Docker Compose (frontend, backend, db, video-stream), MediaMTX + FFmpeg (manual RTSP/HLS relay for local demos) |

**Attribution:** `crowd_models/` is the official PyTorch implementation accompanying *"Video Individual Counting for Moving Drones"* (ICCV 2025 Highlight, [arXiv:2503.10701](https://arxiv.org/abs/2503.10701)). It's included wholesale for its SDNet model code and a pretrained `.pth` checkpoint; only `config.py`, `model/`, and `misc/` (the modules imported transitively by `model/VIC.py`) are used at inference time by `cv_pipeline/sdnet_detector.py`. `datasets/`, `train.py`, `test.py`, and the evaluation/metrics utilities in `misc/` are training/reproduction code for the original paper and are not exercised by the live app.

Note: `backend/app/models/density.py` and `drone.py` declare SQLAlchemy `Base`/`Column` models, but the backend actually talks to the database with raw SQL through `app/db.py` (which also transparently rewrites Postgres-flavoured SQL to SQLite when falling back). The SQLAlchemy models are unused scaffolding — see below.

---

## 🚀 Getting Started

### Prerequisites

To run SkyWatch locally, you will need:
- **Python 3.10 (strictly required)**
- **Node.js 18+** and **npm**
- *(Optional but recommended)* **MediaMTX** and **FFmpeg** for simulating live RTSP streams.
- **Docker** and **Docker Compose** to run the containerized PostgreSQL database.

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

### 3. Start the Database (Dockerized)

SkyWatch uses a containerized PostGIS (PostgreSQL) database. To start it, run:

```bash
docker-compose up -d db
```

---

### 4. Start the FastAPI Backend

The backend connects to the Dockerized database automatically (ensure your `.env` is configured). If the database is completely unavailable, the system safely falls back to a persistent local SQLite database (`skywatch.db`) for testing.

**Linux / macOS:**
```bash
cd backend
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Windows (PowerShell):**
```powershell
cd backend
py -3.10 -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
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
*The dashboard will be available at `http://localhost:5173`.*

---

### 6. Start the CV Stream Processor

The processor acts as the "eyes" of the drone. It connects to a video source, analyzes it, and sends data to the backend. Note: First-time setup may take a few minutes as it downloads PyTorch and model weights.

Open a **new terminal** window:

**Linux / macOS:**
```bash
cd cv_pipeline
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
cd cv_pipeline
py -3.10 -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

#### Option A: Run Simulation (Managed via Frontend)
You don't need to manually start the stream processor for local MP4 files. Simulated drone feeds and crowd analyses can be directly triggered and managed by an Admin via the SkyWatch frontend dashboard. Ensure the backend and frontend are running, log in as an admin, and initiate the simulation directly from the UI.

#### Option B: Run with a Live Drone Stream (RTSP/RTMP/HTTP)
If you have a real drone or are running an RTSP server (like MediaMTX), simply provide the URL. The processor will automatically handle network disconnects and retries.

```bash
python stream_processor.py \
  --source "rtsp://your-drone-ip:554/live" \
  --fps 5 \
  --drone-id DRN-LIVE-01 \
  --drone-name "DJI Mavic 3" \
  --latitude 30.9683 \
  --longitude 76.4732 \
  --altitude 80
```

> **Note:** To run multiple drones simultaneously, simply open additional terminals and run `stream_processor.py` with different `--drone-id`, coordinates, and `--source` values.

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
├── database/         # SQL scripts & database bootstrap
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

### Flagged but kept (by request)

- **`video-stream/`** — the Docker Compose service that's supposed to simulate an RTSP feed. Its only script, `simulate_feed.py`, is an unimplemented stub (`print("Video stream simulator not yet implemented.")`) — the service currently does nothing. Real RTSP simulation is done manually via MediaMTX + FFmpeg per `RUNBOOK.md`. Kept in case it gets finished later.
- **`crowd_models/`'s training/reproduction code** — `datasets/`, `train.py`, `test.py`, `misc/{evaluation_code,KPI_pool,get_bbox,cal_mean,dataparallel,modelsummary,nms,inflation,pos_embed,post_process,tools}.py`, and `model/{PreciseRoIPooling,MatchTool,optimal_transport_layer.py,ViT/models_mae_cross.py}`. Verified by tracing the actual import graph from `model/VIC.py`: none of this is touched at inference time (notably, `PreciseRoIPooling`'s only reference anywhere is inside a fully commented-out training method). Kept intentionally so the paper's original training/eval pipeline stays reproducible and reusable as more models get added here.
- **`backend/app/routers/density.py::get_heatmap_data`** (`GET /api/density/heatmap`) — stub endpoint, always returns `{"points": [], "timestamp": None}`; the frontend builds its heatmap client-side from `/api/density/current` instead. Left as-is since it's a single stub function, not a standalone file.

---

## 📝 License

This project is open-source and available under standard MIT guidelines. Feel free to fork, modify, and integrate into your own fleet management systems.
