import { motion } from 'framer-motion';
import { useGoogleLogin } from '@react-oauth/google';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { loginWithGoogle } from '../lib/api';
import { useState, useEffect } from 'react';
import './LoginPage.css';

export default function LoginPage() {
  const { login, isAuthenticated, addDevice } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
  const [pairCode, setPairCode] = useState('');
  const [targetUrl, setTargetUrl] = useState('');
  const [targetSystemId, setTargetSystemId] = useState('');

  const isGoogleConfigured = !!import.meta.env.VITE_GOOGLE_CLIENT_ID;

  async function fetchTunnelUrl(code) {
    if (code.length !== 6) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`https://fall-detect-832f6-default-rtdb.asia-southeast1.firebasedatabase.app/pair_codes/${code}.json`);
      if (res.ok) {
        const data = await res.json();
        if (data && data.url) {
          setTargetUrl(data.url);
          setTargetSystemId(data.system_id || Date.now().toString());
        } else {
          setError('ไม่พบข้อมูลกล้องสำหรับรหัสนี้');
        }
      } else {
        setError('ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์เพื่อตรวจสอบรหัสได้');
      }
    } catch (e) {
      setError('เกิดข้อผิดพลาดในการตรวจสอบรหัส');
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogleSuccess(tokenResponse) {
    if (!targetUrl) return;
    setLoading(true);
    setError('');
    try {
      const googleCredential = tokenResponse.access_token || tokenResponse.credential;
      const result = await loginWithGoogle(googleCredential, targetUrl);
      login(result.token, result.user, googleCredential);
      addDevice('Camera ' + pairCode, targetUrl, result.token, pairCode, targetSystemId);
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
    if (!targetUrl) return;
    setLoading(true);
    try {
      const result = await loginWithGoogle('dev-mode', targetUrl);
      login(result.token, result.user, 'dev-mode');
      addDevice('Camera ' + pairCode, targetUrl, result.token, pairCode, targetSystemId);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError('ไม่สามารถเชื่อมต่อ API Server ได้');
    } finally {
      setLoading(false);
    }
  }

  const googleLogin = useGoogleLogin({
    onSuccess: handleGoogleSuccess,
    onError: () => setError('Google login ล้มเหลว'),
  });

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

        {/* Pair Code Input */}
        {!targetUrl && (
          <motion.div
            className="login-actions"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.6 }}
            style={{ marginTop: '20px' }}
          >
            <p style={{ color: 'var(--text-secondary)', marginBottom: '10px' }}>กรุณากรอกรหัสเชื่อมต่อ 6 หลัก</p>
            <input
              type="text"
              className="pair-form-input"
              style={{ textAlign: 'center', fontSize: '1.5rem', letterSpacing: '4px' }}
              placeholder="000000"
              maxLength={6}
              value={pairCode}
              onChange={(e) => {
                const val = e.target.value.replace(/\D/g, '');
                setPairCode(val);
                if (val.length === 6) {
                  fetchTunnelUrl(val);
                }
              }}
              disabled={loading}
            />
            {loading && (
              <div style={{ marginTop: '15px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px' }}>
                <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>กำลังค้นหา...</span>
              </div>
            )}
          </motion.div>
        )}

        {/* Login Button */}
        {targetUrl && (
          <motion.div
            className="login-actions"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
          >
            <p style={{ color: '#4CAF50', marginBottom: '16px', fontSize: '14px' }}>
              ✓ พบกล้องแล้ว: {targetUrl.replace('https://', '')}
            </p>
            <button
              className={`login-google-btn ${!isGoogleConfigured ? 'disabled-config' : ''}`}
              onClick={() => {
                if (!isGoogleConfigured) {
                  setError('⚠️ ยังไม่ได้ตั้งค่า Google Client ID ใน .env กรุณาใช้ "เข้าแบบ Developer Mode" แทน');
                  return;
                }
                googleLogin();
              }}
              disabled={loading}
            >
              {loading ? (
                <div className="spinner" style={{ width: 20, height: 20, borderWidth: 2 }} />
              ) : (
                <>
                  <svg className="google-icon" viewBox="0 0 24 24" width="20" height="20">
                    <path fill={isGoogleConfigured ? '#4285F4' : '#888'} d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                    <path fill={isGoogleConfigured ? '#34A853' : '#666'} d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                    <path fill={isGoogleConfigured ? '#FBBC05' : '#777'} d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                    <path fill={isGoogleConfigured ? '#EA4335' : '#555'} d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                  </svg>
                  {isGoogleConfigured ? 'Sign in with Google' : 'Google Sign In (ไม่ได้ตั้งค่า)'}
                </>
              )}
            </button>

            {/* Dev mode button (visible only when GOOGLE_CLIENT_ID is not set) */}
            <button
              className="login-dev-btn"
              onClick={handleDevLogin}
              disabled={loading}
            >
              🔧 เข้าแบบ Developer Mode
            </button>
            
            <button
              className="login-dev-btn"
              style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)' }}
              onClick={() => {
                setTargetUrl('');
                setPairCode('');
              }}
              disabled={loading}
            >
              ยกเลิก
            </button>
          </motion.div>
        )}

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
