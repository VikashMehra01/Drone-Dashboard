import React, { useContext, useState } from "react";
import { SkyForgeContext } from "../context/SkyForgeContext";
import {
  Unlock,
  Lock,
  ShieldAlert,
  ShieldCheck,
  Plane,
  PlaneLanding,
  CornerUpLeft,
  Power,
} from "lucide-react";
import "./FlightControl.css";

export default function FlightControl() {
  const {
    drones,
    selectedDrone,
    setSelectedDrone,
    loading,
    error,
    setError,
    connectDrone,
    disconnectDrone,
    armDrone,
    disarmDrone,
    setMode,
  } = useContext(SkyForgeContext);

  const [connectionString, setConnectionString] = useState("udp:0.0.0.0:14550");
  const [newDroneId, setNewDroneId] = useState("");

  const drone = selectedDrone ? drones[selectedDrone] : null;

  const handleConnect = async (e) => {
    e.preventDefault();
    if (!newDroneId.trim()) {
      setError("Please enter a drone ID");
      return;
    }
    await connectDrone(newDroneId, connectionString);
    setNewDroneId("");
  };

  const handleDisconnect = async () => {
    if (selectedDrone) {
      await disconnectDrone(selectedDrone);
    }
  };

  const handleArm = async () => {
    if (selectedDrone) {
      await armDrone(selectedDrone);
    }
  };

  const handleDisarm = async () => {
    if (selectedDrone) {
      await disarmDrone(selectedDrone);
    }
  };

  const handleModeChange = async (mode) => {
    if (selectedDrone) {
      await setMode(selectedDrone, mode);
    }
  };

  return (
    <>
      <h2 style={{ fontSize: '20px', fontWeight: 700, marginBottom: '20px' }}>
        Flight Control
      </h2>

      {error && (
        <div className="error-banner">
          <span>{error}</span>
          <button onClick={() => setError(null)}>✕</button>
        </div>
      )}

      <div className="flight-control-content">
        {/* Left Panel: Drone Connection */}
        <div className="panel connection-panel">
          <h2>Drone Connection</h2>

          <div className="connection-form">
            <h3>Connect New Drone</h3>
            <form onSubmit={handleConnect}>
              <div className="form-group">
                <label>Drone ID:</label>
                <input
                  type="text"
                  placeholder="e.g., DRN-001, SIM-COPTER"
                  value={newDroneId}
                  onChange={(e) => setNewDroneId(e.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="form-group">
                <label>Connection String:</label>
                <select
                  value={connectionString}
                  onChange={(e) => setConnectionString(e.target.value)}
                  disabled={loading}
                >
                  <option value="udp:0.0.0.0:14550">UDP Port 14550 (Primary GCS)</option>
                  <option value="udp:127.0.0.1:14550">UDP Loopback 14550</option>
                  <option value="tcp:127.0.0.1:5760">TCP 5760 (SITL Simulation)</option>
                  <option value="/dev/ttyUSB0">Serial /dev/ttyUSB0</option>
                  <option value="COM3">Serial COM3 (Windows)</option>
                </select>
              </div>

              <button type="submit" disabled={loading} className="btn-connect">
                {loading ? "Connecting..." : "Connect"}
              </button>
            </form>
          </div>

          <div className="drone-list">
            <h3>
              Connected Drones ({Object.keys(drones).length})
            </h3>
            {Object.keys(drones).length === 0 ? (
              <p className="empty-state">No drones connected</p>
            ) : (
              <div className="drone-items">
                {Object.entries(drones).map(([droneId, telemetry]) => (
                  <div
                    key={droneId}
                    className={`drone-item ${selectedDrone === droneId ? "active" : ""}`}
                    onClick={() => setSelectedDrone(droneId)}
                  >
                    <div className="drone-header">
                      <span className="drone-id">{droneId}</span>
                      <span
                        className={`status-badge ${
                          telemetry.is_armed ? "armed" : "disarmed"
                        }`}
                      >
                        {telemetry.is_armed ? "ARMED" : "SAFE"}
                      </span>
                    </div>
                    <div className="drone-info">
                      <span>Mode: {telemetry.mode}</span>
                      <span>Battery: {telemetry.battery_level?.toFixed(0)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Panel: Flight Control */}
        {drone ? (
          <div className="panel control-panel">
            <h2>Flight Control - {selectedDrone}</h2>

            {/* Telemetry Display */}
            <div className="telemetry-section">
              <h3>Real-Time Telemetry</h3>
              <div className="telemetry-grid">
                <div className="telemetry-item">
                  <label>Position</label>
                  <div className="value">
                    {drone.latitude?.toFixed(4)}°, {drone.longitude?.toFixed(4)}°
                  </div>
                </div>

                <div className="telemetry-item">
                  <label>Altitude (MSL)</label>
                  <div className="value">{drone.altitude_msl?.toFixed(1)} m</div>
                </div>

                <div className="telemetry-item">
                  <label>Altitude (AGL)</label>
                  <div className="value">{drone.altitude_agl?.toFixed(1)} m</div>
                </div>

                <div className="telemetry-item">
                  <label>Battery</label>
                  <div className="value">
                    <div className="battery-bar">
                      <div
                        className="battery-fill"
                        style={{
                          width: `${drone.battery_level}%`,
                          backgroundColor:
                            drone.battery_level > 50
                              ? "var(--color-accent-green)"
                              : drone.battery_level > 20
                              ? "var(--color-accent-amber)"
                              : "var(--color-accent-red)",
                        }}
                      />
                    </div>
                    {drone.battery_level?.toFixed(0)}%
                  </div>
                </div>

                <div className="telemetry-item">
                  <label>Airspeed</label>
                  <div className="value">{drone.airspeed?.toFixed(1)} m/s</div>
                </div>

                <div className="telemetry-item">
                  <label>Groundspeed</label>
                  <div className="value">{drone.groundspeed?.toFixed(1)} m/s</div>
                </div>

                <div className="telemetry-item">
                  <label>Roll</label>
                  <div className="value">{drone.roll?.toFixed(1)}°</div>
                </div>

                <div className="telemetry-item">
                  <label>Pitch</label>
                  <div className="value">{drone.pitch?.toFixed(1)}°</div>
                </div>

                <div className="telemetry-item">
                  <label>Yaw</label>
                  <div className="value">{drone.yaw?.toFixed(1)}°</div>
                </div>

                <div className="telemetry-item">
                  <label>Mode</label>
                  <div className="value">{drone.mode}</div>
                </div>

                <div className="telemetry-item">
                  <label>Battery Voltage</label>
                  <div className="value">{drone.battery_voltage?.toFixed(2)} V</div>
                </div>

                <div className="telemetry-item">
                  <label>Battery Current</label>
                  <div className="value">{drone.battery_current?.toFixed(2)} A</div>
                </div>
              </div>
            </div>

            {/* Flight Mode Selection */}
            <div className="control-section">
              <h3>Flight Mode</h3>
              <div className="mode-buttons">
                {["STABILIZE", "ALT_HOLD", "GUIDED", "LOITER", "RTL", "LAND"].map(
                  (mode) => (
                    <button
                      key={mode}
                      className={`mode-btn ${drone.mode === mode ? "active" : ""}`}
                      onClick={() => handleModeChange(mode)}
                      disabled={loading}
                    >
                      {mode}
                    </button>
                  )
                )}
              </div>
            </div>

            {/* Arm/Disarm Controls */}
            <div className="control-section">
              <h3>Motor Control</h3>
              <div className="arm-controls">
                <button
                  className="btn btn-arm"
                  onClick={handleArm}
                  disabled={drone.is_armed || loading}
                  style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
                >
                  {drone.is_armed ? <ShieldCheck size={14} /> : <Unlock size={14} />}
                  {drone.is_armed ? "ARMED" : "ARM"}
                </button>
                <button
                  className="btn btn-disarm"
                  onClick={handleDisarm}
                  disabled={!drone.is_armed || loading}
                  style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
                >
                  {!drone.is_armed ? <ShieldCheck size={14} /> : <Lock size={14} />}
                  {!drone.is_armed ? "DISARMED" : "DISARM"}
                </button>
              </div>
            </div>

            {/* Emergency Actions */}
            <div className="control-section emergency">
              <h3>Emergency</h3>
              <button
                className="btn btn-emergency"
                onClick={() => handleModeChange("LAND")}
                disabled={loading}
                style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
              >
                <PlaneLanding size={14} />
                LAND NOW
              </button>
              <button
                className="btn btn-emergency"
                onClick={() => handleModeChange("RTL")}
                disabled={loading}
                style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
              >
                <CornerUpLeft size={14} />
                RETURN TO LAUNCH
              </button>
              <button
                className="btn btn-disconnect"
                onClick={handleDisconnect}
                disabled={loading}
                style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
              >
                <Power size={14} />
                DISCONNECT
              </button>
            </div>
          </div>
        ) : (
          <div className="panel control-panel empty">
            <h2>Flight Control</h2>
            <div className="empty-state">
              <p>🚁 Select a drone to view controls</p>
              <p>Connect a drone first to get started</p>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
