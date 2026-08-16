# SkyWatch – Real-time Drone Surveillance Portal

<div align="center">
  <h3>Real-time crowd-density monitoring using drone video streams, CV-based person detection, FastAPI APIs, and a modern React + Leaflet dashboard.</h3>
</div>

---

## 📖 Overview

**SkyWatch** is a comprehensive fleet management and surveillance platform designed to ingest and analyze live drone video streams. By applying advanced Computer Vision (CV) models on the incoming feeds, it estimates crowd density and provides actionable intelligence in real time. 

The system features a sleek, interactive dashboard that visualizes active drone assets on a live map, highlights dense crowds via heatmaps, displays live video feeds inline, and tracks telemetry across the fleet.

### ✨ Key Features

- **Multi-Protocol Video Ingestion**: Supports real-time drone feeds via RTSP, RTMP, HTTP MJPEG, or simulated streams from local `.mp4` files.
- **AI-Powered Crowd Density**: Utilizes deep learning models (SDNet or YOLO) via PyTorch to accurately estimate headcounts in live frames.
- **Dynamic Heatmaps & Telemetry**: Renders live drone coordinates, altitude, battery status, and geospatial crowd heatmaps directly onto a Leaflet-based map.
- **Resilient Backend architecture**: Powered by FastAPI with automatic fallback to an in-memory SQLite database if a production PostgreSQL instance is unavailable.
- **Telegram Alert Integration**: Automatic push notifications to security personnel when anomalous activity or extreme crowd density is detected.
- **Sleek React Dashboard**: A modern Vite + React frontend featuring live HLS video playback, dark/light mode toggles, and dynamic UI filtering.

---

## 🏗 System Architecture

The project is structured into three primary micro-services:

1. **`frontend/`** (Vite + React + Tailwind CSS / MUI)
   - The interactive dashboard. Connects to the backend API to fetch drone telemetry and fetches live HLS video feeds (re-broadcasted from MediaMTX) to display directly in the browser.
2. **`backend/`** (FastAPI + SQLAlchemy)
   - The central nervous system. Receives POST requests from the CV processors containing headcounts and coordinates, and serves this state to the frontend via REST endpoints.
3. **`drone_heatmap_backend/`** (Python + PyTorch + OpenCV)
   - The CV stream processor. Connects to the raw video source (RTSP/file), runs the frames through the selected AI model, and posts the density data to the backend.

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
cd drone_heatmap_backend
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
cd drone_heatmap_backend
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
├── backend/                # FastAPI application & API routers
├── frontend/               # Vite + React Dashboard (Tailwind + MUI + Leaflet)
├── drone_heatmap_backend/  # PyTorch CV pipeline & stream processing daemon
├── media/                  # Sample video files for local simulation
├── database/               # SQL scripts & database bootstrap
├── .env.example            # Environment variables template
├── README.md               # You are here
└── RUNBOOK.md              # Advanced guide for simulating live RTSP streams
```

## 📝 License

This project is open-source and available under standard MIT guidelines. Feel free to fork, modify, and integrate into your own fleet management systems.
