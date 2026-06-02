import { motion } from 'framer-motion';
import LiveBadge from './LiveBadge';
import StatusChip from './StatusChip';
import './CameraCard.css';

export default function CameraCard({ ip, name, frame, status, onClick }) {
  const isFall = status && status.includes('FALL');

  return (
    <motion.div
      className={`camera-card glass-card ${isFall ? 'camera-card-alert' : ''}`}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
    >
      {/* Header */}
      <div className="camera-card-header">
        <div className="camera-card-info">
          <span className="camera-card-icon">📷</span>
          <span className="camera-card-name">{name || ip}</span>
        </div>
        <LiveBadge />
      </div>

      {/* Feed */}
      <div className="camera-card-feed">
        {frame ? (
          <img
            src={`data:image/jpeg;base64,${frame}`}
            alt={`Camera ${name}`}
            className="camera-card-image"
            loading="lazy"
          />
        ) : (
          <div className="camera-card-placeholder">
            <div className="spinner" />
            <span>กำลังโหลด...</span>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="camera-card-footer">
        <StatusChip status={status} />
        <span className="camera-card-ip">{ip}</span>
      </div>
    </motion.div>
  );
}
