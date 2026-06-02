import { useState, useEffect, useRef, useCallback } from 'react';
import { getFrames, getCameras } from '../lib/api';

/**
 * Hook for polling live camera frames.
 * @param {number} intervalMs - Polling interval in milliseconds (default 1500ms)
 * @param {boolean} enabled - Whether polling is active
 */
export function useCameraFeed(intervalMs = 1500, enabled = true) {
  const [frames, setFrames] = useState({});
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  const fetchData = useCallback(async () => {
    try {
      const [framesData, camerasData] = await Promise.all([
        getFrames(),
        getCameras(),
      ]);
      setFrames(framesData);
      setCameras(camerasData);
      setError(null);
      setLoading(false);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;

    // Initial fetch
    fetchData();

    // Start polling
    intervalRef.current = setInterval(fetchData, intervalMs);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [enabled, intervalMs, fetchData]);

  return { frames, cameras, loading, error };
}
