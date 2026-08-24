# SkyForge + HeatMap Integration Guide

## Overview

SkyForge GCS (Ground Control Station) is now integrated into the HeatMap dashboard as a **headless service**. Instead of running SkyForge's PyQt desktop GUI, its telemetry and control capabilities are now exposed as **FastAPI REST endpoints** that the React dashboard can consume.

**Result**: A single unified web interface showing both:
- ✈️ Drone flight status (MAVLink telemetry)
- 👥 Crowd density monitoring (CV analysis)
- 📍 Real-time drone positions on map
- 🎯 Flight control and mission planning

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│              React Web Dashboard                          │
│      (HeatMap Frontend on http://localhost:5173)          │
│  - Crowd Density Heatmap                                 │
│  - Drone Positions & Status                              │
│  - Flight Control Panel (NEW)                            │
│  - Camera Feeds (CV + RTSP)                              │
└─────────────────┬──────────────────────────────────────┘
                  │ HTTP REST / WebSocket
   ┌──────────────┴──────────────┬──────────────────┐
   │                              │                  │
┌──▼──────────────┐    ┌─────────▼────┐    ┌───────▼────┐
│  HeatMap        │    │  SkyForge    │    │ CV Pipeline│
│  FastAPI        │    │  FastAPI     │    │            │
│  Backend        │    │  (Telemetry) │    │            │
│                 │    │              │    │            │
│ /api/drones     │    │ /api/skyforge│    │            │
│ /api/density/*  │    │ /telemetry/* │    │            │
│ /api/alerts     │    │ /control/*   │    │            │
└────────┬────────┘    └──────┬───────┘    └────────────┘
         │                    │
         └────────┬───────────┘
                  │ SQLite
          ┌───────▼────────┐
          │   Database     │
          │  (skywatch.db) │
          └────────────────┘

        MAVLink (UDP/TCP)
              ▲
              │
        ┌─────┴──────┐
        │   Drone    │
        │ (Pixhawk)  │
        └────────────┘
```

---

## Setup

### 1. Install Dependencies

The required packages are already in `backend/requirements.txt`. If you haven't installed them yet:

```bash
cd /Users/sarvansuthar/Downloads/Drone-Dashboard-main/HeatMap/backend
pip install -r requirements.txt
```

**Key packages added:**
- `pymavlink>=2.4` — MAVLink protocol library
- `scipy==1.10.1` — For gimbal quaternion parsing

### 2. Start HeatMap Backend

```bash
cd /Users/sarvansuthar/Downloads/Drone-Dashboard-main/HeatMap/backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The backend now includes **SkyForge telemetry endpoints** under `/api/skyforge`.

Verify:
```bash
curl http://localhost:8000/api/skyforge/health
```

Expected response:
```json
{
  "status": "healthy",
  "connected_drones": 0,
  "timestamp": "2024-01-15T10:30:45.123456"
}
```

---

## Using SkyForge Telemetry Endpoints

### Connect to a Drone

```bash
curl -X POST "http://localhost:8000/api/skyforge/telemetry/connect" \
  -G -d "drone_id=DRN-001" \
  -d "connection_string=udp:0.0.0.0:14550"
```

**Connection string formats:**
| Format | Example | Description |
|--------|---------|-------------|
| UDP | `udp:0.0.0.0:14550` | Primary GCS port (Pixhawk default) |
| UDP Loopback | `udp:127.0.0.1:14550` | Local testing |
| TCP | `tcp:127.0.0.1:5760` | Simulated flight (SITL) |
| Serial | `/dev/ttyUSB0` | Direct USB connection to FC |
| Serial (Win) | `COM3:57600` | Windows COM port |

### Get Real-Time Telemetry

```bash
curl "http://localhost:8000/api/skyforge/telemetry/current?drone_id=DRN-001"
```

Response:
```json
{
  "drone_id": "DRN-001",
  "timestamp": "2024-01-15T10:30:45.123456",
  "latitude": 30.9683,
  "longitude": 76.4732,
  "altitude_msl": 85.5,
  "altitude_agl": 80.2,
  "roll": 5.2,
  "pitch": -2.1,
  "yaw": 125.4,
  "airspeed": 12.5,
  "groundspeed": 13.1,
  "battery_level": 87.0,
  "battery_voltage": 10.8,
  "battery_current": 5.3,
  "is_armed": true,
  "is_flying": true,
  "mode": "GUIDED",
  "gimbal_pitch": -45.0,
  "gimbal_roll": 0.0,
  "gimbal_yaw": 0.0
}
```

### List All Connected Drones

```bash
curl "http://localhost:8000/api/skyforge/connected-drones"
```

### Flight Control

**Arm drone:**
```bash
curl -X POST "http://localhost:8000/api/skyforge/control/arm?drone_id=DRN-001"
```

**Disarm drone:**
```bash
curl -X POST "http://localhost:8000/api/skyforge/control/disarm?drone_id=DRN-001"
```

**Set flight mode:**
```bash
curl -X POST "http://localhost:8000/api/skyforge/control/mode" \
  -G -d "drone_id=DRN-001" \
  -d "mode=GUIDED"
```

**Available modes:** `STABILIZE`, `ACRO`, `ALT_HOLD`, `AUTO`, `GUIDED`, `LOITER`, `RTL`, `CIRCLE`, `POSHOLD`, `BRAKE`, `LAND`

### Disconnect

```bash
curl -X POST "http://localhost:8000/api/skyforge/telemetry/disconnect?drone_id=DRN-001"
```

---

## Frontend Integration (React)

### 1. Create SkyForge Context

Create a new file `frontend/src/context/SkyForgeContext.jsx`:

```jsx
import React, { createContext, useState, useEffect, useCallback } from "react";

export const SkyForgeContext = createContext();

export const SkyForgeProvider = ({ children }) => {
  const [drones, setDrones] = useState({});
  const [selectedDrone, setSelectedDrone] = useState(null);
  const [loading, setLoading] = useState(false);

  const API_BASE = "http://localhost:8000/api/skyforge";

  // Fetch telemetry for all drones
  const fetchAllTelemetry = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/telemetry/all`);
      const data = await response.json();
      
      const droneMap = {};
      data.forEach(telemetry => {
        droneMap[telemetry.drone_id] = telemetry;
      });
      setDrones(droneMap);
    } catch (error) {
      console.error("Error fetching telemetry:", error);
    }
  }, []);

  // Poll telemetry every 2 seconds
  useEffect(() => {
    fetchAllTelemetry();
    const interval = setInterval(fetchAllTelemetry, 2000);
    return () => clearInterval(interval);
  }, [fetchAllTelemetry]);

  const connectDrone = useCallback(async (droneId, connectionString) => {
    setLoading(true);
    try {
      const response = await fetch(
        `${API_BASE}/telemetry/connect?drone_id=${droneId}&connection_string=${connectionString}`,
        { method: "POST" }
      );
      const result = await response.json();
      await fetchAllTelemetry();
      return result;
    } catch (error) {
      console.error("Error connecting drone:", error);
    } finally {
      setLoading(false);
    }
  }, [fetchAllTelemetry]);

  const armDrone = useCallback(async (droneId) => {
    try {
      const response = await fetch(
        `${API_BASE}/control/arm?drone_id=${droneId}`,
        { method: "POST" }
      );
      return await response.json();
    } catch (error) {
      console.error("Error arming drone:", error);
    }
  }, []);

  const disarmDrone = useCallback(async (droneId) => {
    try {
      const response = await fetch(
        `${API_BASE}/control/disarm?drone_id=${droneId}`,
        { method: "POST" }
      );
      return await response.json();
    } catch (error) {
      console.error("Error disarming drone:", error);
    }
  }, []);

  const setMode = useCallback(async (droneId, mode) => {
    try {
      const response = await fetch(
        `${API_BASE}/control/mode?drone_id=${droneId}&mode=${mode}`,
        { method: "POST" }
      );
      return await response.json();
    } catch (error) {
      console.error("Error setting mode:", error);
    }
  }, []);

  return (
    <SkyForgeContext.Provider
      value={{
        drones,
        selectedDrone,
        setSelectedDrone,
        loading,
        connectDrone,
        armDrone,
        disarmDrone,
        setMode,
      }}
    >
      {children}
    </SkyForgeContext.Provider>
  );
};
```

### 2. Create Flight Control Panel Component

Create `frontend/src/components/FlightControlPanel.jsx`:

```jsx
import React, { useContext, useState } from "react";
import { SkyForgeContext } from "../context/SkyForgeContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export const FlightControlPanel = () => {
  const { drones, selectedDrone, setSelectedDrone, armDrone, disarmDrone, setMode } = useContext(SkyForgeContext);
  const [connectionString, setConnectionString] = useState("udp:0.0.0.0:14550");

  const drone = drones[selectedDrone];

  if (!drone) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Flight Control</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-gray-500">No drone connected</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-slate-900 border-blue-500">
      <CardHeader>
        <CardTitle className="text-blue-400">Flight Control - {selectedDrone}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Telemetry Display */}
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-400">Altitude (MSL):</span>
            <p className="font-bold text-white">{drone.altitude_msl?.toFixed(1)} m</p>
          </div>
          <div>
            <span className="text-gray-400">Battery:</span>
            <p className="font-bold text-white">{drone.battery_level?.toFixed(0)}%</p>
          </div>
          <div>
            <span className="text-gray-400">Mode:</span>
            <p className="font-bold text-white">{drone.mode}</p>
          </div>
          <div>
            <span className="text-gray-400">Armed:</span>
            <p className={`font-bold ${drone.is_armed ? "text-red-500" : "text-green-500"}`}>
              {drone.is_armed ? "✓ ARMED" : "DISARMED"}
            </p>
          </div>
        </div>

        {/* Control Buttons */}
        <div className="grid grid-cols-2 gap-2">
          <Button
            onClick={() => armDrone(selectedDrone)}
            disabled={drone.is_armed}
            className="bg-green-600 hover:bg-green-700"
          >
            ARM
          </Button>
          <Button
            onClick={() => disarmDrone(selectedDrone)}
            disabled={!drone.is_armed}
            className="bg-red-600 hover:bg-red-700"
          >
            DISARM
          </Button>
          <Button
            onClick={() => setMode(selectedDrone, "LAND")}
            className="bg-orange-600 hover:bg-orange-700 col-span-2"
          >
            LAND
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};
```

### 3. Update Main App

In `frontend/src/App.jsx`, wrap with `SkyForgeProvider` and add the control panel:

```jsx
import { SkyForgeProvider } from "./context/SkyForgeContext";
import { FlightControlPanel } from "./components/FlightControlPanel";

function App() {
  return (
    <SkyForgeProvider>
      <div>
        {/* Existing dashboard components */}
        <FlightControlPanel />
        {/* Other components */}
      </div>
    </SkyForgeProvider>
  );
}
```

---

## Testing Workflow

### Option 1: SITL (Software-in-the-Loop) Simulation

Perfect for testing without hardware:

```bash
# Terminal 1: Start SITL simulator
# Download SITL: https://ardupilot.org/dev/building-setup-linux.html
sim_vehicle.py -v ArduCopter --console --map
```

This starts a simulated Pixhawk on `localhost:5760`

```bash
# Terminal 2: Connect HeatMap to simulated drone
curl -X POST "http://localhost:8000/api/skyforge/telemetry/connect" \
  -G -d "drone_id=SIM-COPTER-01" \
  -d "connection_string=tcp:127.0.0.1:5760"
```

```bash
# Terminal 3: Monitor telemetry
watch -n 1 'curl -s "http://localhost:8000/api/skyforge/telemetry/current?drone_id=SIM-COPTER-01" | jq'
```

### Option 2: Real Hardware (Pixhawk + Serial)

```bash
# Connect Pixhawk via USB and find device:
ls /dev/tty*  # Look for /dev/ttyUSB0 or /dev/ttyACM0

# Connect:
curl -X POST "http://localhost:8000/api/skyforge/telemetry/connect" \
  -G -d "drone_id=PIXHAWK-01" \
  -d "connection_string=/dev/ttyUSB0"
```

### Option 3: QGroundControl Forwarding

If QGroundControl is already running on port 14550:

```bash
# Create UDP forwarder (MAVProxy):
mavproxy.py --master=:14550 --out=127.0.0.1:14551

# Connect HeatMap to forwarded port:
curl -X POST "http://localhost:8000/api/skyforge/telemetry/connect" \
  -G -d "drone_id=DRONE-01" \
  -d "connection_string=udp:127.0.0.1:14551"
```

---

## What's Implemented

✅ **Phase 1 Complete:**
- [x] MAVLink telemetry service (arm/disarm, modes, telemetry)
- [x] FastAPI endpoints for SkyForge
- [x] Drone connection/disconnection
- [x] Flight control (arm, disarm, set mode)
- [x] Real-time telemetry polling
- [x] Health checks

🚧 **Phase 2 In Progress:**
- [ ] React components for flight control
- [ ] Map integration (drone marker + flight path)
- [ ] Real-time telemetry gauges
- [ ] Mission planning UI

📋 **Phase 3 Future:**
- [ ] Mission upload/execution
- [ ] Gimbal control
- [ ] Waypoint navigation
- [ ] Geofencing

---

## API Reference

See the interactive API documentation at:
```
http://localhost:8000/docs
```

The `/api/skyforge` endpoints are documented with request/response schemas.

---

## Troubleshooting

**Q: "pymavlink not installed"**
```bash
pip install pymavlink
```

**Q: "Failed to establish MAVLink connection"**
- Check connection string format
- Verify drone is powered on
- Check firewall/port blocking (port 14550 is common)

**Q: "Connection timeout"**
- Try loopback first: `udp:127.0.0.1:14550`
- Verify MAVLink device is broadcasting

**Q: Telemetry shows all zeros**
- Wait 5-10 seconds for first GPS lock
- Check drone has satellite fix

---

## Next Steps

1. **Test connectivity** with simulated drone (SITL)
2. **Add Flight Control tab** to React dashboard
3. **Overlay drone position** on HeatMap
4. **Display telemetry gauges** (altitude, battery, speed)
5. **Implement mission planning** UI

Questions? Check the main README or API docs at `/docs`!
