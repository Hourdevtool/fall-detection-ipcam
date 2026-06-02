import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useCameraFeed } from '../hooks/useCameraFeed';
import { getPairStatus } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import CameraCard from '../components/CameraCard';
import './DashboardPage.css';

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [paired, setPaired] = useState(null); // null = loading
  const { frames, cameras, loading, error } = useCameraFeed(1500, paired === true);

  // Check pairing status on mount
  useEffect(() => {
    getPairStatus()
      .then((status) => {
        if (!status.is_paired) {
          navigate('/pair', { replace: true });
        } else {
          setPaired(true);
        }
      })
      .catch(() => {
        // API might not be available; allow access anyway in dev
        setPaired(true);
      });
  }, [navigate]);

  if (paired === null) {
    return (
      <div className="page" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
        <div className="spinner" />
      </div>
    );
  }

  const cameraEntries = Object.entries(frames);

  return (
    <div className="page">
      {/* Header */}
      <div className="dashboard-header">
        <div>
          <h1 className="page-title">🛡️ Fall Guard</h1>
          <p className="page-subtitle">
            {cameras.length > 0
              ? `${cameras.length} กล้องออนไลน์`
              : 'กำลังค้นหากล้อง...'
            }
          </p>
        </div>
        <button className="dashboard-avatar" onClick={logout} title="ออกจากระบบ">
          {user?.picture ? (
            <img src={user.picture} alt={user.name} />
          ) : (
            <span>👤</span>
          )}
        </button>
      </div>

      {/* Camera Grid */}
      {loading && cameraEntries.length === 0 ? (
        <div className="dashboard-loading">
          <div className="skeleton" style={{ height: 200, borderRadius: 16 }} />
          <div className="skeleton" style={{ height: 200, borderRadius: 16, marginTop: 16 }} />
        </div>
      ) : cameraEntries.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📡</div>
          <div className="empty-state-title">ไม่พบกล้อง</div>
          <div className="empty-state-text">
            ระบบกำลังสแกนหากล้องในเครือข่าย<br />กรุณารอสักครู่...
          </div>
        </div>
      ) : (
        <motion.div className="camera-grid" layout>
          <AnimatePresence>
            {cameraEntries.map(([ip, frame], index) => {
              const camera = cameras.find((c) => c.ip === ip);
              return (
                <CameraCard
                  key={ip}
                  ip={ip}
                  name={camera?.name || ip}
                  frame={frame}
                  status={null}
                />
              );
            })}
          </AnimatePresence>
        </motion.div>
      )}

      {error && (
        <div className="dashboard-error">
          ⚠️ {error}
        </div>
      )}
    </div>
  );
}
