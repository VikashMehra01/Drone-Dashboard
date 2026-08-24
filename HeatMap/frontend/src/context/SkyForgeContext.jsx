import React, { createContext, useState, useEffect, useCallback } from "react";

export const SkyForgeContext = createContext();

export const SkyForgeProvider = ({ children }) => {
  const [drones, setDrones] = useState({});
  const [selectedDrone, setSelectedDrone] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const API_BASE = "http://localhost:8000/api/skyforge";

  // Fetch telemetry for all drones
  const fetchAllTelemetry = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/telemetry/all`);
      const data = await response.json();

      const droneMap = {};
      data.forEach((telemetry) => {
        droneMap[telemetry.drone_id] = telemetry;
      });
      setDrones(droneMap);
      setError(null);
    } catch (error) {
      console.error("Error fetching telemetry:", error);
      setError("Failed to fetch telemetry");
    }
  }, []);

  // Poll telemetry every 2 seconds
  useEffect(() => {
    fetchAllTelemetry();
    const interval = setInterval(fetchAllTelemetry, 2000);
    return () => clearInterval(interval);
  }, [fetchAllTelemetry]);

  const connectDrone = useCallback(
    async (droneId, connectionString) => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(
          `${API_BASE}/telemetry/connect?drone_id=${droneId}&connection_string=${connectionString}`,
          { method: "POST" }
        );
        const result = await response.json();
        if (response.ok) {
          setSelectedDrone(droneId);
          await fetchAllTelemetry();
        } else {
          setError(result.detail || "Connection failed");
        }
        return result;
      } catch (error) {
        console.error("Error connecting drone:", error);
        setError("Connection error: " + error.message);
      } finally {
        setLoading(false);
      }
    },
    [fetchAllTelemetry]
  );

  const disconnectDrone = useCallback(async (droneId) => {
    try {
      const response = await fetch(
        `${API_BASE}/telemetry/disconnect?drone_id=${droneId}`,
        { method: "POST" }
      );
      const result = await response.json();
      if (selectedDrone === droneId) {
        setSelectedDrone(null);
      }
      await fetchAllTelemetry();
      return result;
    } catch (error) {
      console.error("Error disconnecting drone:", error);
      setError("Disconnection error: " + error.message);
    }
  }, [selectedDrone, fetchAllTelemetry]);

  const armDrone = useCallback(async (droneId) => {
    try {
      const response = await fetch(
        `${API_BASE}/control/arm?drone_id=${droneId}`,
        { method: "POST" }
      );
      const result = await response.json();
      if (response.ok) {
        await fetchAllTelemetry();
      }
      return result;
    } catch (error) {
      console.error("Error arming drone:", error);
      setError("Arm error: " + error.message);
    }
  }, [fetchAllTelemetry]);

  const disarmDrone = useCallback(async (droneId) => {
    try {
      const response = await fetch(
        `${API_BASE}/control/disarm?drone_id=${droneId}`,
        { method: "POST" }
      );
      const result = await response.json();
      if (response.ok) {
        await fetchAllTelemetry();
      }
      return result;
    } catch (error) {
      console.error("Error disarming drone:", error);
      setError("Disarm error: " + error.message);
    }
  }, [fetchAllTelemetry]);

  const setMode = useCallback(
    async (droneId, mode) => {
      try {
        const response = await fetch(
          `${API_BASE}/control/mode?drone_id=${droneId}&mode=${mode}`,
          { method: "POST" }
        );
        const result = await response.json();
        if (response.ok) {
          await fetchAllTelemetry();
        }
        return result;
      } catch (error) {
        console.error("Error setting mode:", error);
        setError("Mode set error: " + error.message);
      }
    },
    [fetchAllTelemetry]
  );

  return (
    <SkyForgeContext.Provider
      value={{
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
      }}
    >
      {children}
    </SkyForgeContext.Provider>
  );
};
