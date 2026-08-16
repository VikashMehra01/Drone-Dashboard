# Loop Control Configuration

## Overview
The SkyWatch system now supports dynamic video looping control. Videos can be configured to loop continuously or play once and stop.

## Configuration

### 1. **stream_config.py** (Macros File)
Located at: `drone_heatmap_backend/stream_config.py`

Contains all centralized flags and defaults:
```python
DEFAULT_LOOP_VIDEO = True          # Set to False for one-pass playback
DEFAULT_FPS = 5                    # Video processing frame rate
DEFAULT_DRONE_ID = "DRN-001"       # Default drone identifier
# ... more constants for API endpoints, detection tuning, etc.
```

### 2. **Stream Processor**
Located at: `drone_heatmap_backend/stream_processor.py`

Accepts `--loop` flag:
```bash
# With looping (default, video repeats)
python stream_processor.py --source "http://localhost:8000/videos/droneVid.mp4" --loop true

# One-pass playback (video plays once)
python stream_processor.py --source "http://localhost:8000/videos/droneVid.mp4" --loop false
```

### 3. **Backend API**
Located at: `backend/app/routers/density.py`

- Stores `loop_video` preference in density update payload
- Returns `loop_video` in `/api/density/current` response
- Frontend reads this value and applies it to video elements

### 4. **Frontend Components**

#### DroneFeed.jsx
- Tracks `loopVideo` state
- Updates from backend preference
- Applies `loop={loopVideo}` to video element

#### MapView.jsx
- Tracks `loopVideo` state
- Updates from backend preference in fetchDensity()
- Applies `loop={loopVideo}` to modal video player

## Data Flow

```
Stream Processor --[loop_video in payload]--> Backend --[loop_video in API response]--> Frontend --[loop={loopVideo}]--> Video Element
```

## Usage Examples

### Start with loop disabled (one-pass playback)
```bash
cd /home/vikash-mehra/Tree/Drone/SkyWatch/drone_heatmap_backend
source ../backend/venv/bin/activate
python stream_processor.py \
  --source "http://localhost:8000/videos/droneVid.mp4" \
  --drone-id DRN-001 \
  --drone-name "Alpha-1" \
  --zone "Connaught Place" \
  --latitude 28.6139 \
  --longitude 77.2090 \
  --altitude 120 \
  --fps 5 \
  --loop false
```

### Start with loop enabled (continuous playback)
```bash
python stream_processor.py \
  --source "http://localhost:8000/videos/droneVid.mp4" \
  --drone-id DRN-001 \
  --drone-name "Alpha-1" \
  --zone "Connaught Place" \
  --latitude 28.6139 \
  --longitude 77.2090 \
  --altitude 120 \
  --fps 5 \
  --loop true
```

## Files Modified

1. **backend/app/config.py** - Added STREAM_STALE_SECONDS, ALLOW_DEBUG_PLAYBACK, MEDIA_VIDEOS_DIR
2. **backend/app/routers/density.py** - Extended DensityUpdate model with loop_video field
3. **backend/app/routers/drone.py** - One-active source matching logic
4. **drone_heatmap_backend/stream_config.py** - NEW: Centralized macros file
5. **drone_heatmap_backend/stream_processor.py** - Added --loop parameter and loop_video payload
6. **frontend/src/pages/DroneFeed.jsx** - Added loopVideo state, reads from backend
7. **frontend/src/components/MapView.jsx** - Added loopVideo state, reads from backend, applies to modal video

## Testing

1. **Terminal 1**: Start backend
   ```bash
   cd /home/vikash-mehra/Tree/Drone/SkyWatch/backend
   source venv/bin/activate
   uvicorn app.main:app --reload
   ```

2. **Terminal 2**: Start frontend
   ```bash
   cd /home/vikash-mehra/Tree/Drone/SkyWatch/frontend
   npm run dev
   ```

3. **Terminal 3**: Start stream processor with desired loop setting
   ```bash
   cd /home/vikash-mehra/Tree/Drone/SkyWatch/drone_heatmap_backend
   source ../backend/venv/bin/activate
   python stream_processor.py --source "http://localhost:8000/videos/droneVid.mp4" --loop false
   ```

4. **Verify**: Open http://localhost:5173, click on drone feed card or map marker to see video with loop setting applied








source ../backend/venv/bin/activate
python stream_processor.py \
  --source "http://localhost:8000/videos/droneVid3.mp4" \
  --drone-id DRN-007 \
  --drone-name "Alpha-3" \
  --zone "Connaught Place dkflasd" \
  --latitude 38.6139 \
  --longitude 77.2090 \
  --altitude 120 \
  --fps 5 \
  --loop true