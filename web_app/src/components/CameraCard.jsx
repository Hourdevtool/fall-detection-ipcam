import { motion } from 'framer-motion';
import LiveBadge from './LiveBadge';
import StatusChip from './StatusChip';
import './CameraCard.css';

export default function CameraCard({ ip, name, edgeUrl, status, onClick }) {
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
        {edgeUrl ? (
          <img
            src={`${edgeUrl}/api/stream/${ip}`}
            alt={`Camera ${name}`}
            className="camera-card-image"
            loading="lazy"
            onError={(e) => { e.target.style.display = 'none'; }}
          />
        ) : (
          <div className="camera-card-placeholder">
            <div className="spinner" />
            <span>กำลังเชื่อมต่อใหม่...</span>
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
