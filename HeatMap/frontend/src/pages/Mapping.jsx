import React, { useState, useEffect, useCallback, useRef } from "react";
import { RotateCcw, RefreshCw, Layers, MapPin } from "lucide-react";
import "./Mapping.css";

const API_BASE = "http://localhost:8000/api/mapping";
const POLL_MS = 3000;

export default function Mapping() {
  const [status, setStatus] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [error, setError] = useState(null);
  const [resetting, setResetting] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [imgTick, setImgTick] = useState(Date.now());
  const [mapAvailable, setMapAvailable] = useState(true);
  const pollRef = useRef(null);

  const fetchState = useCallback(async () => {
    try {
      const [statusRes, coverageRes] = await Promise.all([
        fetch(`${API_BASE}/status`),
        fetch(`${API_BASE}/coverage`),
      ]);
      if (!statusRes.ok || !coverageRes.ok) throw new Error("Backend returned an error");
      setStatus(await statusRes.json());
      setCoverage(await coverageRes.json());
      setError(null);
    } catch (err) {
      console.error("Error fetching mapping state:", err);
      setError("Cannot reach mapping API — is the backend running?");
    }
  }, []);

  useEffect(() => {
    fetchState();
    pollRef.current = setInterval(() => {
      fetchState();
      if (autoRefresh) {
        setMapAvailable(true);
        setImgTick(Date.now());
      }
    }, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [fetchState, autoRefresh]);

  const handleReset = async () => {
    if (!window.confirm("Reset the mapper? This clears the current stitched map and session stats.")) return;
    setResetting(true);
    try {
      const res = await fetch(`${API_BASE}/reset`, { method: "POST" });
      if (!res.ok) throw new Error("Reset failed");
      setMapAvailable(true);
      setImgTick(Date.now());
      await fetchState();
    } catch (err) {
      console.error("Error resetting mapper:", err);
      setError("Reset failed: " + err.message);
    } finally {
      setResetting(false);
    }
  };

  const handleManualRefresh = () => {
    setMapAvailable(true);
    setImgTick(Date.now());
    fetchState();
  };

  const stat = (label, value) => (
    <div className="mapping-stat">
      <label>{label}</label>
      <div className="value">{value}</div>
    </div>
  );

  return (
    <>
      <h2 style={{ fontSize: "20px", fontWeight: 700, marginBottom: "20px" }}>
        Orthomosaic Mapping
      </h2>

      {error && (
        <div className="error-banner">
          <span>{error}</span>
          <button onClick={() => setError(null)}>✕</button>
        </div>
      )}

      <div className="mapping-content">
        {/* Left Panel: Session Stats */}
        <div className="panel mapping-stats-panel">
          <h2>Session Stats</h2>

          <div className="mapping-stats-grid">
            {stat("Frames Processed", status?.n_frames ?? 0)}
            {stat("Tile Count", status?.tile_count ?? 0)}
            {stat("Tile Memory", `${(status?.tile_memory_mb ?? 0).toFixed(1)} MB`)}
            {stat("Coverage Area", `${(status?.area_m2 ?? 0).toFixed(0)} m²`)}
            {stat("FPS", (status?.fps ?? 0).toFixed(2))}
            {stat("Avg Frame Time", `${(status?.avg_total_ms ?? 0).toFixed(0)} ms`)}
          </div>

          <h3 style={{ marginTop: "20px" }}>Coverage</h3>
          <div className="mapping-coverage-summary">
            <div className="coverage-row">
              <MapPin size={13} />
              <span>{coverage?.frame_count ?? 0} footprints tracked</span>
            </div>
            <div className="coverage-row">
              <Layers size={13} />
              <span>{(coverage?.area_m2 ?? 0).toFixed(0)} m² union area</span>
            </div>
          </div>

          <div className="mapping-controls">
            <label className="mapping-toggle">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Auto-refresh map ({POLL_MS / 1000}s)
            </label>

            <button className="btn btn-refresh" onClick={handleManualRefresh}>
              <RefreshCw size={14} />
              Refresh Now
            </button>

            <button className="btn btn-emergency" onClick={handleReset} disabled={resetting}>
              <RotateCcw size={14} />
              {resetting ? "Resetting…" : "Reset Map"}
            </button>
          </div>

          <p className="mapping-hint">
            Feed offline frames with{" "}
            <code>python scripts/replay_mapping_frames.py --dir &lt;frames&gt;</code>
          </p>
        </div>

        {/* Right Panel: Stitched Map */}
        <div className="panel mapping-view-panel">
          <h2>Stitched Map</h2>
          <div className="mapping-image-frame">
            {mapAvailable ? (
              <img
                key={imgTick}
                src={`${API_BASE}/latest?t=${imgTick}`}
                alt="Stitched orthomosaic map"
                onError={() => setMapAvailable(false)}
              />
            ) : (
              <div className="mapping-empty-state">
                <p>🗺️ No map data yet</p>
                <p>Feed some frames, then hit "Refresh Now"</p>
                <button className="btn btn-refresh" onClick={() => { setMapAvailable(true); handleManualRefresh(); }}>
                  <RefreshCw size={14} />
                  Try Again
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
