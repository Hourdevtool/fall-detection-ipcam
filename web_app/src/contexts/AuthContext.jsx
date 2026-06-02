import { createContext, useContext, useState, useEffect } from 'react';
import { getMe } from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('fallguard_token'));
  const [loading, setLoading] = useState(true);

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

  function login(newToken, userData) {
    localStorage.setItem('fallguard_token', newToken);
    localStorage.setItem('fallguard_user', JSON.stringify(userData));
    setToken(newToken);
    setUser(userData);
  }

  function logout() {
    localStorage.removeItem('fallguard_token');
    localStorage.removeItem('fallguard_user');
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, login, logout, isAuthenticated: !!token }}>
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
