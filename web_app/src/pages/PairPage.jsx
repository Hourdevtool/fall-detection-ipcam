import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import PairCodeInput from '../components/PairCodeInput';
import { submitPairCode } from '../lib/api';
import './PairPage.css';

export default function PairPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  async function handleComplete(code) {
    setLoading(true);
    setError('');
    try {
      await submitPairCode(code);
      setSuccess(true);
      // Navigate to dashboard after brief animation
      setTimeout(() => navigate('/dashboard', { replace: true }), 1500);
    } catch (err) {
      setError(err.message || 'รหัสไม่ถูกต้องหรือหมดอายุ');
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
              <h1 className="pair-title">จับคู่อุปกรณ์</h1>
              <p className="pair-subtitle">
                กรอกรหัส 6 หลักที่แสดงบนหน้าจอของระบบตรวจจับ<br />
                เพื่อเชื่อมต่อกับอุปกรณ์ของคุณ
              </p>
            </div>

            {/* Code Input */}
            <div className="pair-input-section">
              <PairCodeInput onComplete={handleComplete} />
              
              {loading && (
                <div className="pair-loading">
                  <div className="spinner" style={{ width: 24, height: 24, borderWidth: 2 }} />
                  <span>กำลังตรวจสอบ...</span>
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

            {/* Help text */}
            <div className="pair-help">
              <div className="pair-help-item">
                <span className="pair-help-step">1</span>
                <span>เปิดระบบ Fall Guard บนคอมพิวเตอร์</span>
              </div>
              <div className="pair-help-item">
                <span className="pair-help-step">2</span>
                <span>ดูรหัส 6 หลักที่แสดงบนหน้าจอ</span>
              </div>
              <div className="pair-help-item">
                <span className="pair-help-step">3</span>
                <span>กรอกรหัสในช่องด้านบน</span>
              </div>
            </div>
          </>
        )}
      </motion.div>
    </div>
  );
}
