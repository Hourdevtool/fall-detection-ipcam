import { useState, useEffect, useRef, useCallback } from 'react';
import { getCameras } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

/**
 * Hook for polling live camera frames.
 * @param {number} intervalMs - Polling interval in milliseconds (default 1500ms)
 * @param {boolean} enabled - Whether polling is active
 */
export function useCameraFeed(intervalMs = 1500, enabled = true) {
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
      setCameras(camerasData);
      setError(null);
      setLoading(false);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }, [activeDevice]);

  useEffect(() => {
    if (!enabled || !activeDevice) {
      setLoading(false);
      return;
    }

    // Initial fetch
    fetchData();

    // Start polling
    intervalRef.current = setInterval(fetchData, intervalMs);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [enabled, intervalMs, fetchData, activeDevice]);

  return { cameras, loading, error };
}

