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
      // Verify token is still valid
      getMe()
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
  }, [token]);

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

  function removeDevice(deviceId) {
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
      selectDevice,
      removeDevice
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

