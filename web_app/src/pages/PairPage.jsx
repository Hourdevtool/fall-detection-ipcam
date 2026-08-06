import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import PairCodeInput from '../components/PairCodeInput';
import { useAuth, FIREBASE_DB } from '../contexts/AuthContext';
import { loginWithGoogle, submitPairCode } from '../lib/api';
import './PairPage.css';

export default function PairPage() {
  const navigate = useNavigate();
  const { user, googleCredential, addDeviceToState, devices } = useAuth();
  
  const [deviceName, setDeviceName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  async function handleComplete(code) {
    if (!deviceName.trim()) {
      setError('กรุณากรอกชื่ออุปกรณ์');
      return;
    }

    setLoading(true);
    setError('');
    try {
      // 1. ค้นหา Cloudflare URL จาก Firebase โดยใช้รหัส 6 หลัก
      const fbRes = await fetch(`https://fall-detect-832f6-default-rtdb.asia-southeast1.firebasedatabase.app/pair_codes/${code}.json`);
      const pairData = await fbRes.json();

      if (!pairData || !pairData.system_id) {
        throw new Error('ไม่พบรหัสอุปกรณ์นี้บนเซิร์ฟเวอร์ หรือรหัสหมดอายุ');
      }

      const sysRes = await fetch(`https://fall-detect-832f6-default-rtdb.asia-southeast1.firebasedatabase.app/systems/${pairData.system_id}.json`);
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
      if (!pairRes.success) throw new Error("Pairing failed on edge server");

      // 4. Save device to Firebase RTDB for the current user
      if (user) {
        await fetch(`${FIREBASE_DB}/users/${user.sub}/devices/${systemId}.json`, {
          method: 'PUT',
          body: JSON.stringify({
            name: deviceName.trim(),
            added_at: Date.now()
          })
        });
      }

      // 5. Add to local state
      addDeviceToState({
        id: systemId,
        name: deviceName.trim(),
        ip: cloudflareUrl,
        token: edgeToken
      });
      
      setSuccess(true);
      setTimeout(() => navigate('/dashboard', { replace: true }), 1500);
    } catch (err) {
      setError(err.message || 'รหัสไม่ถูกต้อง หรือไม่สามารถเชื่อมต่ออุปกรณ์ได้');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pair-page">
      <motion.div
        className="pair-content"
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        {success ? (
          <motion.div
            className="pair-success"
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', stiffness: 200 }}
          >
            <div className="pair-success-icon">✅</div>
            <h2 className="pair-success-title">จับคู่สำเร็จ!</h2>
            <p className="pair-success-text">กำลังเข้าสู่หน้าหลัก...</p>
          </motion.div>
        ) : (
          <>
            {/* Header */}
            <div className="pair-header">
              <span className="pair-icon">🔗</span>
              <h1 className="pair-title">เพิ่ม/จับคู่อุปกรณ์ใหม่</h1>
              <p className="pair-subtitle">
                เชื่อมต่อระบบตรวจจับกล้องเพื่อติดตามผ่านมือถือ
              </p>
            </div>

            {/* Inputs */}
            <div className="pair-form">
              <div className="pair-form-group">
                <label className="pair-form-label">ชื่ออุปกรณ์ / สถานที่</label>
                <input
                  type="text"
                  className="pair-form-input"
                  placeholder="เช่น บ้านคุณยาย, ห้องนั่งเล่น"
                  value={deviceName}
                  onChange={(e) => setDeviceName(e.target.value)}
                  disabled={loading}
                />
              </div>

              {/* Code Input */}
              <div className="pair-input-section">
                <label className="pair-form-label" style={{ marginBottom: 12 }}>กรอกรหัสจับคู่ 6 หลัก</label>
                <PairCodeInput onComplete={handleComplete} />
                
                {loading && (
                  <div className="pair-loading">
                    <div className="spinner" style={{ width: 24, height: 24, borderWidth: 2 }} />
                    <span>กำลังค้นหากล้องและตรวจสอบรหัส...</span>
                  </div>
                )}

                {error && (
                  <motion.p
                    className="pair-error"
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                  >
                    ❌ {error}
                  </motion.p>
                )}
              </div>
            </div>

            {/* Actions */}
            {devices.length > 0 && (
              <button
                type="button"
                className="pair-cancel-btn"
                onClick={() => navigate('/dashboard')}
                disabled={loading}
              >
                ย้อนกลับ
              </button>
            )}

            {/* Help text */}
            <div className="pair-help" style={{ marginTop: 24 }}>
              <div className="pair-help-item">
                <span className="pair-help-step">1</span>
                <span>เปิดระบบบนคอมพิวเตอร์กล้อง</span>
              </div>
              <div className="pair-help-item">
                <span className="pair-help-step">2</span>
                <span>ดูรหัส 6 หลักบนหน้าจอกล้อง</span>
              </div>
              <div className="pair-help-item">
                <span className="pair-help-step">3</span>
                <span>กรอกรหัส 6 หลักเพื่อจับคู่ทันที</span>
              </div>
            </div>
          </>
        )}
      </motion.div>
    </div>
  );
}

