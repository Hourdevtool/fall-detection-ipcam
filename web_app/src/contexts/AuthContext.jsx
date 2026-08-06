import { createContext, useContext, useState, useEffect } from 'react';
import { jwtDecode } from 'jwt-decode';
import { loginWithGoogle, unpair } from '../lib/api';

const AuthContext = createContext(null);
export const FIREBASE_DB = 'https://fall-detect-832f6-default-rtdb.asia-southeast1.firebasedatabase.app';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [googleCredential, setGoogleCredential] = useState(localStorage.getItem('google_credential'));
  const [devices, setDevices] = useState([]);
  const [activeDevice, setActiveDevice] = useState(null);
  const [loading, setLoading] = useState(true);

  // 1. Load User from googleCredential on Mount
  useEffect(() => {
    if (googleCredential) {
      try {
        if (googleCredential === 'dev-mode') {
          setUser({
            sub: 'dev_user_001',
            name: 'Developer',
            email: 'dev@fallguard.local',
            picture: ''
          });
        } else {
          const decoded = jwtDecode(googleCredential);
          setUser(decoded);
        }
      } catch (e) {
        console.error("Invalid token:", e);
        logout();
      }
    } else {
      setLoading(false);
    }
  }, [googleCredential]);

  // 2. Fetch Devices and Authenticate to Edge Servers
  useEffect(() => {
    if (!user) {
      setDevices([]);
      setActiveDevice(null);
      return;
    }

    let isMounted = true;
    const fetchUserDevices = async () => {
      try {
        // Fetch list of system_ids paired to this user
        const res = await fetch(`${FIREBASE_DB}/users/${user.sub}/devices.json`);
        const data = await res.json();
        
        if (!data) {
          if (isMounted) {
             setDevices([]);
             setLoading(false);
          }
          return;
        }

        const deviceEntries = Object.entries(data); // [ [system_id, { name, added_at }], ... ]
        
        // Fetch URLs for each system_id and authenticate
        const loadedDevices = await Promise.all(
          deviceEntries.map(async ([systemId, devInfo]) => {
            try {
              const sysRes = await fetch(`${FIREBASE_DB}/systems/${systemId}.json`);
              const sysData = await sysRes.json();
              const url = sysData?.url || '';

              let edgeToken = '';
              if (url) {
                // Exchange google credential for edge server token
                try {
                  const authRes = await loginWithGoogle(googleCredential, url);
                  edgeToken = authRes.token;
                } catch(e) {
                  console.warn(`Could not auth with ${url}`, e);
                }
              }

              return {
                id: systemId,
                name: devInfo.name,
                ip: url,
                token: edgeToken,
              };
            } catch(e) {
               return null;
            }
          })
        );
        
        const validDevices = loadedDevices.filter(Boolean);
        if (isMounted) {
          setDevices(validDevices);
          
          // Restore active device or set to first
          const savedActiveId = localStorage.getItem('fallguard_active_device_id');
          if (savedActiveId && validDevices.find(d => d.id === savedActiveId)) {
            setActiveDevice(validDevices.find(d => d.id === savedActiveId));
          } else if (validDevices.length > 0) {
            setActiveDevice(validDevices[0]);
          }
        }
      } catch (error) {
        console.error("Failed to load user devices", error);
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchUserDevices();
    
    // Auto refresh URLs every 5 mins
    const interval = setInterval(fetchUserDevices, 300000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [user, googleCredential]);

  // Save active device
  useEffect(() => {
    if (activeDevice) {
      localStorage.setItem('fallguard_active_device_id', activeDevice.id);
    } else {
      localStorage.removeItem('fallguard_active_device_id');
    }
  }, [activeDevice]);

  async function login(credential) {
    localStorage.setItem('google_credential', credential);
    setGoogleCredential(credential);
    // User effect will trigger, decode token, and fetch devices
  }

  function logout() {
    localStorage.removeItem('google_credential');
    localStorage.removeItem('fallguard_active_device_id');
    setGoogleCredential(null);
    setUser(null);
    setDevices([]);
    setActiveDevice(null);
  }

  function selectDevice(device) {
    setActiveDevice(device);
  }

  // Exposed for PairPage
  function addDeviceToState(newDevice) {
    const updated = [...devices.filter(d => d.id !== newDevice.id), newDevice];
    setDevices(updated);
    if (!activeDevice) setActiveDevice(newDevice);
  }

  async function removeDevice(deviceId) {
    const device = devices.find(d => d.id === deviceId);
    if (device && device.token) {
      try {
        await unpair(device);
      } catch (e) {
        console.error("Failed to unpair on backend", e);
      }
    }
    
    // Remove from Firebase RTDB
    if (user) {
      try {
        await fetch(`${FIREBASE_DB}/users/${user.sub}/devices/${deviceId}.json`, {
          method: 'DELETE'
        });
      } catch (e) {
         console.error("Failed to delete from Firebase", e);
      }
    }

    const updated = devices.filter(d => d.id !== deviceId);
    setDevices(updated);

    if (activeDevice?.id === deviceId) {
      setActiveDevice(updated.length > 0 ? updated[0] : null);
    }
  }

  function updateDeviceName(deviceId, newName) {
    // Also update in Firebase
    if (user) {
      fetch(`${FIREBASE_DB}/users/${user.sub}/devices/${deviceId}.json`, {
        method: 'PATCH',
        body: JSON.stringify({ name: newName })
      }).catch(e => console.error(e));
    }

    const updated = devices.map(d => 
      d.id === deviceId ? { ...d, name: newName } : d
    );
    setDevices(updated);

    if (activeDevice?.id === deviceId) {
      setActiveDevice(updated.find(d => d.id === deviceId));
    }
  }

  return (
    <AuthContext.Provider value={{
      user,
      token: googleCredential, // Used for legacy compatibility if needed
      googleCredential,
      loading,
      login,
      logout,
      isAuthenticated: !!user,
      devices,
      activeDevice,
      selectDevice,
      removeDevice,
      updateDeviceName,
      addDeviceToState
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
