import { motion } from 'framer-motion';
import { GoogleLogin } from '@react-oauth/google';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useState, useEffect } from 'react';
import './LoginPage.css';

export default function LoginPage() {
  const { login, isAuthenticated, addDevice } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
  const isGoogleConfigured = !!import.meta.env.VITE_GOOGLE_CLIENT_ID;

  async function handleGoogleSuccess(tokenResponse) {
    setLoading(true);
    setError('');
    try {
      const googleCredential = tokenResponse.access_token || tokenResponse.credential;
      // The user successfully logged into Google.
      // We will parse the credential inside AuthContext's login() method.
      await login(googleCredential);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError('เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่');
      console.error('Login error:', err);
    } finally {
      setLoading(false);
    }
  }

  // Dev mode: skip Google auth
  async function handleDevLogin() {
    setLoading(true);
    try {
      await login('dev-mode');
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError('เกิดข้อผิดพลาด');
    } finally {
      setLoading(false);
    }
  }



  // Safe redirection via useEffect to avoid rendering side-effects
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  // Prevent rendering if authenticated (waiting for redirection)
  if (isAuthenticated) {
    return null;
  }

  return (
    <div className="login-page">
      {/* Background glow effects */}
      <div className="login-bg-glow login-bg-glow-1" />
      <div className="login-bg-glow login-bg-glow-2" />

      <motion.div
        className="login-content"
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
      >
        {/* Logo */}
        <motion.div
          className="login-logo"
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ delay: 0.2, duration: 0.6, type: 'spring' }}
        >
          <div className="login-logo-icon">🛡️</div>
          <div className="login-logo-glow" />
        </motion.div>

        {/* Title */}
        <motion.h1
          className="login-title"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4 }}
          style={{ fontSize: '1.2rem', whiteSpace: 'normal', wordBreak: 'break-word', padding: '0 10px' }}
        >
          เครื่องประมวลผลภาพอัจฉริยะเพื่อตรวจจับและแจ้งเตือนการล้มของผู้สูงอายุภายในบ้านด้วยปัญญาประดิษฐ์ (AI) ผ่านระบบไลน์
        </motion.h1>

        <motion.p
          className="login-subtitle"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
        >
          ระบบเฝ้าระวังการล้ม<br />สำหรับผู้สูงอายุ
        </motion.p>

        {/* Login Button */}
        <motion.div
          className="login-actions"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          style={{ marginTop: '30px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}
        >
          {isGoogleConfigured ? (
            <div style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
              <GoogleLogin
                onSuccess={handleGoogleSuccess}
                onError={() => setError('Google login ล้มเหลว')}
                useOneTap
                theme="filled_black"
                shape="pill"
              />
            </div>
          ) : (
            <button className="login-google-btn disabled-config" disabled>
              ⚠️ ยังไม่ได้ตั้งค่า Google Client ID
            </button>
          )}

          {/* Dev mode button (visible only when GOOGLE_CLIENT_ID is not set) */}
          <button
            className="login-dev-btn"
            onClick={handleDevLogin}
            disabled={loading}
            style={{ marginTop: '0' }}
          >
            🔧 เข้าแบบ Developer Mode
          </button>
        </motion.div>

        {error && (
          <motion.p
            className="login-error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
          >
            {error}
          </motion.p>
        )}

        <motion.p
          className="login-version"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1 }}
        >
          v1.0
        </motion.p>
      </motion.div>
    </div>
  );
}
