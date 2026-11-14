import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import PairCodeInput from '../components/PairCodeInput';
import ThemeToggle from '../components/ThemeToggle';
import { useAuth, FIREBASE_DB } from '../contexts/AuthContext';
import { loginWithGoogle, submitPairCode } from '../lib/api';
import {
  BrandLogo,
  IconLink,
  IconCheckCircle,
  IconAlert,
  IconArrowLeft,
} from '../components/Icons';
import './PairPage.css';

export default function PairPage() {
  const navigate = useNavigate();
  const { user, googleCredential, addDeviceToState, devices } = useAuth();

  const [deviceName, setDeviceName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const nameInputRef = useRef(null);

  async function handleComplete(code) {
    if (!deviceName.trim()) {
      setError('กรุณากรอกชื่ออุปกรณ์หรือสถานที่ก่อน เช่น บ้านคุณยาย');
      nameInputRef.current?.focus();
      return;
    }

    setLoading(true);
    setError('');
    try {
      // 1. ค้นหา Cloudflare URL จาก Firebase โดยใช้รหัส 6 หลัก
      const fbRes = await fetch(`${FIREBASE_DB}/pair_codes/${code}.json`);
      const pairData = await fbRes.json();

      if (!pairData || !pairData.system_id) {
        throw new Error('ไม่พบรหัสอุปกรณ์นี้บนเซิร์ฟเวอร์ หรือรหัสหมดอายุ');
      }

      const sysRes = await fetch(`${FIREBASE_DB}/systems/${pairData.system_id}.json`);
      const sysData = await sysRes.json();

      if (!sysData || !sysData.url) {
        throw new Error('อุปกรณ์ยังไม่ได้เชื่อมต่ออินเทอร์เน็ต (ไม่มี URL)');
      }

      const cloudflareUrl = sysData.url;
      const systemId = pairData.system_id;

      // 2. Authenticate to Edge Server
      const authRes = await loginWithGoogle(googleCredential, cloudflareUrl);
      const edgeToken = authRes.token;

      // 3. Submit pair code to Edge Server
      const pairRes = await submitPairCode(code, { ip: cloudflareUrl, token: edgeToken });
      if (!pairRes.success) throw new Error('การจับคู่บนอุปกรณ์หลักไม่สำเร็จ');

      // 4. Save device to Firebase RTDB for the current user
      if (user) {
        await fetch(`${FIREBASE_DB}/users/${user.sub}/devices/${systemId}.json`, {
          method: 'PUT',
          body: JSON.stringify({
            name: deviceName.trim(),
            added_at: Date.now(),
          }),
        });
      }

      // 5. Add to local state
      addDeviceToState({
        id: systemId,
        name: deviceName.trim(),
        ip: cloudflareUrl,
        token: edgeToken,
      });

      setSuccess(true);
      setTimeout(() => navigate('/dashboard', { replace: true }), 1400);
    } catch (err) {
      setError(err.message || 'รหัสไม่ถูกต้อง หรือไม่สามารถเชื่อมต่ออุปกรณ์ได้');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pair-page">
      {/* Top Bar */}
      <header className="pair-topbar">
        <div className="pair-topbar-left">
          {devices.length > 0 ? (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => navigate('/dashboard')}
              disabled={loading}
            >
              <IconArrowLeft size={16} />
              <span>กลับหน้าหลัก</span>
            </button>
          ) : (
            <div className="pair-topbar-brand">
              <BrandLogo size={30} />
              <span>FallGuard AI</span>
            </div>
          )}
        </div>
        <ThemeToggle variant="segmented" />
      </header>

      <main className="pair-main">
        {success ? (
          <motion.div
            className="pair-success glass-card"
            initial={{ scale: 0.94, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', stiffness: 240, damping: 22 }}
          >
            <div className="pair-success-icon">
              <IconCheckCircle size={36} />
            </div>
            <h1 className="pair-success-title">จับคู่อุปกรณ์สำเร็จ</h1>
            <p className="pair-success-text">
              เชื่อมต่อกับ “{deviceName.trim()}” เรียบร้อยแล้ว กำลังเข้าสู่หน้าดูภาพสด...
            </p>
          </motion.div>
        ) : (
          <div className="pair-layout">
            {/* Form Card */}
            <motion.section
              className="pair-card glass-card"
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4 }}
            >
              <div className="pair-header">
                <div className="pair-icon-wrap">
                  <IconLink size={24} />
                </div>
                <h1 className="pair-title">เพิ่ม / จับคู่อุปกรณ์ใหม่</h1>
                <p className="pair-subtitle">
                  เชื่อมต่อระบบตรวจจับกล้องบนเครื่อง เพื่อดูภาพสดและแจ้งเตือนผ่านเว็บ
                </p>
              </div>

              <div className="pair-form">
                <div className="pair-form-group">
                  <label htmlFor="pair-device-name" className="pair-form-label">
                    ชื่ออุปกรณ์ / สถานที่ติดตั้ง
                  </label>
                  <input
                    ref={nameInputRef}
                    id="pair-device-name"
                    type="text"
                    className="input-field"
                    placeholder="เช่น บ้านคุณยาย, ห้องนั่งเล่นชั้นล่าง"
                    value={deviceName}
                    onChange={(e) => {
                      setDeviceName(e.target.value);
                      if (error) setError('');
                    }}
                    disabled={loading}
                  />
                </div>

                <div className="pair-input-section">
                  <span className="pair-form-label">กรอกรหัสจับคู่ 6 หลัก</span>
                  <p className="pair-helper-hint">เมื่อกรอกครบ 6 หลัก ระบบจะเชื่อมต่ออัตโนมัติ</p>
                  <PairCodeInput onComplete={handleComplete} disabled={loading} />

                  {loading && (
                    <div className="pair-loading">
                      <div className="spinner" style={{ width: 20, height: 20, borderWidth: 2 }} />
                      <span>กำลังค้นหาเครื่องและตรวจสอบรหัส...</span>
                    </div>
                  )}

                  {error && (
                    <motion.div
                      className="pair-error"
                      role="alert"
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0 }}
                    >
                      <IconAlert size={16} />
                      <span>{error}</span>
                    </motion.div>
                  )}
                </div>
              </div>
            </motion.section>

            {/* Guide Panel */}
            <motion.aside
              className="pair-help glass-card"
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.08 }}
            >
              <h2 className="pair-help-heading">ขั้นตอนการเชื่อมต่อ</h2>
              <div className="pair-help-list">
                <div className="pair-help-item">
                  <span className="pair-help-step mono">1</span>
                  <div>
                    <strong>เปิดโปรแกรม FallGuard บนเครื่อง</strong>
                    <p>ตรวจสอบว่าเครื่องเชื่อมต่ออินเทอร์เน็ตและกล้องเรียบร้อยแล้ว</p>
                  </div>
                </div>
                <div className="pair-help-item">
                  <span className="pair-help-step mono">2</span>
                  <div>
                    <strong>ดูรหัสจับคู่ 6 หลักบนหน้าจอ</strong>
                    <p>รหัสจะแสดงอยู่ที่แถบด้านบนหรือหน้าต่าง QR Code ของโปรแกรม</p>
                  </div>
                </div>
                <div className="pair-help-item">
                  <span className="pair-help-step mono">3</span>
                  <div>
                    <strong>ตั้งชื่ออุปกรณ์และกรอกรหัส 6 หลัก</strong>
                    <p>สามารถเพิ่มได้หลายเครื่องเพื่อสลับดูกล้องได้จากบัญชีเดียว</p>
                  </div>
                </div>
              </div>
            </motion.aside>
          </div>
        )}
      </main>
    </div>
  );
}
