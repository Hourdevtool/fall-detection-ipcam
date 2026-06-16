import { createContext, useContext, useState, useEffect } from 'react';
import { getMe, loginWithGoogle, submitPairCode } from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('fallguard_token'));
  const [loading, setLoading] = useState(true);

  // Multi-device state
  const [devices, setDevices] = useState(() => {
    try {
      const saved = localStorage.getItem('fallguard_devices');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  const [activeDevice, setActiveDevice] = useState(() => {
    try {
      const saved = localStorage.getItem('fallguard_active_device');
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (token) {
      if (!activeDevice) {
        setLoading(false);
        return;
      }
      // Verify token is still valid against the active device
      getMe(activeDevice)
        .then((userData) => {
          setUser(userData);
          setLoading(false);
        })
        .catch(() => {
          // Token invalid
          logout();
          setLoading(false);
        });
    } else {
      setLoading(false);
    }
  }, [token, activeDevice]);

  // --- Auto-Refresh Cloudflare URLs ---
  useEffect(() => {
    const refreshDeviceUrls = async () => {
      if (!devices || devices.length === 0) return;

      let updated = false;
      const newDevices = [...devices];

      for (let i = 0; i < newDevices.length; i++) {
        const device = newDevices[i];
        if (device.pair_code) {
          try {
            const res = await fetch(`https://fall-detect-832f6-default-rtdb.asia-southeast1.firebasedatabase.app/pair_codes/${device.pair_code}.json`);
            const data = await res.json();
            if (data && data.url && data.url !== device.ip) {
              console.log(`[Auto-Refresh] อัปเดต URL ของกล้อง ${device.name} เป็น ${data.url}`);
              device.ip = data.url;
              updated = true;
            }
          } catch (e) {
            console.error(`[Auto-Refresh] ไม่สามารถอัปเดต URL ของกล้อง ${device.name} ได้`, e);
          }
        }
      }

      if (updated) {
        setDevices(newDevices);
        localStorage.setItem('fallguard_devices', JSON.stringify(newDevices));

        // ถ้า activeDevice ก็เปลี่ยนด้วย ให้ใช้ reference เดียวกันหรือหาใหม่
        if (activeDevice) {
          const newActive = newDevices.find(d => d.id === activeDevice.id);
          if (newActive) {
            setActiveDevice(newActive);
            localStorage.setItem('fallguard_active_device', JSON.stringify(newActive));
          }
        }
      }
    };

    refreshDeviceUrls();
    // Refresh URLs periodically (e.g., every 5 minutes)
    const interval = setInterval(refreshDeviceUrls, 300000);
    return () => clearInterval(interval);
  }, [devices, activeDevice]);

  function login(newToken, userData, googleCredential = null) {
    localStorage.setItem('fallguard_token', newToken);
    localStorage.setItem('fallguard_user', JSON.stringify(userData));
    if (googleCredential) {
      localStorage.setItem('google_credential', googleCredential);
    }
    setToken(newToken);
    setUser(userData);
  }

  function logout() {
    localStorage.removeItem('fallguard_token');
    localStorage.removeItem('fallguard_user');
    localStorage.removeItem('google_credential');
    localStorage.removeItem('fallguard_devices');
    localStorage.removeItem('fallguard_active_device');
    setToken(null);
    setUser(null);
    setDevices([]);
    setActiveDevice(null);
  }

  function addDevice(name, ip, deviceToken, pairCode, systemId) {
    const newDevice = {
      id: systemId || Date.now().toString(),
      name,
      ip,
      token: deviceToken,
      pair_code: pairCode,
    };
    const updatedDevices = [...devices.filter(d => d.id !== newDevice.id), newDevice];
    setDevices(updatedDevices);
    localStorage.setItem('fallguard_devices', JSON.stringify(updatedDevices));
    if (!activeDevice) {
      setActiveDevice(newDevice);
      localStorage.setItem('fallguard_active_device', JSON.stringify(newDevice));
    }
  }

  // Device management functions
  async function pairNewDevice(name, ip, code) {
    // 1. Try to login to the target server to get its JWT token
    const googleCred = localStorage.getItem('google_credential') || 'dev-mode';
    const authResult = await loginWithGoogle(googleCred, ip);
    const deviceToken = authResult.token;

    // 2. Submit the pairing code to the target server using the new token
    const tempDevice = { ip, token: deviceToken };
    const pairResult = await submitPairCode(code, tempDevice);

    if (pairResult.success) {
      const newDevice = {
        id: pairResult.system_id || Date.now().toString(),
        name,
        ip,
        token: deviceToken,
        pair_code: code, // เซฟคู่กับ Device เผื่อเอาไว้อัปเดต Cloudflare URL ภายหลัง
      };

      const updatedDevices = [...devices.filter(d => d.id !== newDevice.id), newDevice];
      setDevices(updatedDevices);
      localStorage.setItem('fallguard_devices', JSON.stringify(updatedDevices));

      // Auto-set as active device if none is active
      if (!activeDevice) {
        setActiveDevice(newDevice);
        localStorage.setItem('fallguard_active_device', JSON.stringify(newDevice));
      }
      return newDevice;
    } else {
      throw new Error("Pairing failed");
    }
  }

  function selectDevice(device) {
    setActiveDevice(device);
    localStorage.setItem('fallguard_active_device', JSON.stringify(device));
  }

  async function removeDevice(deviceId) {
    const device = devices.find(d => d.id === deviceId);
    if (device) {
      try {
        await unpair(device);
      } catch (e) {
        console.error("Failed to unpair on backend", e);
      }
    }
    const updated = devices.filter(d => d.id !== deviceId);
    setDevices(updated);
    localStorage.setItem('fallguard_devices', JSON.stringify(updated));

    if (activeDevice?.id === deviceId) {
      const nextActive = updated.length > 0 ? updated[0] : null;
      setActiveDevice(nextActive);
      if (nextActive) {
        localStorage.setItem('fallguard_active_device', JSON.stringify(nextActive));
      } else {
        localStorage.removeItem('fallguard_active_device');
      }
    }
  }

  function updateDeviceName(deviceId, newName) {
    const updated = devices.map(d => 
      d.id === deviceId ? { ...d, name: newName } : d
    );
    setDevices(updated);
    localStorage.setItem('fallguard_devices', JSON.stringify(updated));

    if (activeDevice?.id === deviceId) {
      const nextActive = updated.find(d => d.id === deviceId);
      setActiveDevice(nextActive);
      localStorage.setItem('fallguard_active_device', JSON.stringify(nextActive));
    }
  }

  return (
    <AuthContext.Provider value={{
      user,
      token,
      loading,
      login,
      logout,
      isAuthenticated: !!token,
      devices,
      activeDevice,
      pairNewDevice,
      addDevice,
      selectDevice,
      removeDevice,
      updateDeviceName
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

