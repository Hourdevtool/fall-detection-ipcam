import { useState, useEffect, useRef, useCallback } from 'react';
import { getCameras } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

/**
 * Hook for polling live camera list & status.
 * @param {number} intervalMs - Polling interval in milliseconds (default 5000ms)
 * @param {boolean} enabled - Whether polling is active
 */
export function useCameraFeed(intervalMs = 5000, enabled = true) {
  const { activeDevice } = useAuth();

  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  const fetchData = useCallback(async () => {
    if (!activeDevice) {
      setCameras([]);
      setLoading(false);
      return;
    }

    try {
      const camerasData = await getCameras(activeDevice);
      setCameras(Array.isArray(camerasData) ? camerasData : []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [activeDevice]);

  useEffect(() => {
    if (!enabled || !activeDevice) {
      return;
    }

    let cancelled = false;
    const run = async () => {
      if (!cancelled) {
        await fetchData();
      }
    };

    run();
    intervalRef.current = setInterval(run, intervalMs);

    return () => {
      cancelled = true;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [enabled, intervalMs, fetchData, activeDevice]);

  return {
    cameras: enabled && activeDevice ? cameras : [],
    loading: enabled && activeDevice ? loading : false,
    error: enabled && activeDevice ? error : null,
    refresh: fetchData,
  };
}
