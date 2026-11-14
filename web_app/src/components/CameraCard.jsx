import { useState } from 'react';
import { motion } from 'framer-motion';
import LiveBadge from './LiveBadge';
import StatusChip from './StatusChip';
import { IconVideo, IconMaximize, IconRefresh, IconWifiOff } from './Icons';
import './CameraCard.css';

function StreamImage({ src, alt }) {
  const [status, setStatus] = useState('loading'); // 'loading' | 'ready' | 'error'

  if (status === 'error') {
    return (
      <div className="camera-card-placeholder">
        <IconWifiOff size={26} />
        <span className="camera-placeholder-title">ไม่พบสัญญาณภาพ</span>
        <span className="camera-placeholder-sub">กล้องอาจออฟไลน์หรือกำลังเชื่อมต่อใหม่</span>
      </div>
    );
  }

  return (
    <>
      {status === 'loading' && (
        <div className="camera-card-loading-overlay">
          <div className="spinner" />
          <span>กำลังเชื่อมต่อสตรีม...</span>
        </div>
      )}
      <img
        src={src}
        alt={alt}
        className={`camera-card-image ${status === 'ready' ? 'visible' : 'hidden'}`}
        onLoad={() => setStatus('ready')}
        onError={() => setStatus('error')}
      />
    </>
  );
}

export default function CameraCard({ ip, name, edgeUrl, hasFrame = true, status, onExpand }) {
  const [retryCount, setRetryCount] = useState(0);
  const isFall = status && status.includes('FALL');
  const cleanEdgeUrl = edgeUrl ? (edgeUrl.startsWith('http') ? edgeUrl : `http://${edgeUrl}`) : '';
  const streamSrc = cleanEdgeUrl ? `${cleanEdgeUrl}/api/stream/${ip}?r=${retryCount}` : '';

  const openExpanded = () => {
    onExpand?.({ ip, name, edgeUrl: cleanEdgeUrl, hasFrame, status });
  };

  function handleRetry() {
    setRetryCount((c) => c + 1);
  }

  return (
    <motion.article
      className={`camera-card glass-card ${isFall ? 'camera-card-alert' : ''}`}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      {/* Header */}
      <div className="camera-card-header">
        <div className="camera-card-info">
          <span className="camera-card-icon-wrap">
            <IconVideo size={16} />
          </span>
          <div className="camera-card-titles">
            <span className="camera-card-name">{name || ip}</span>
            <span className="camera-card-ip mono">{ip}</span>
          </div>
        </div>
        <div className="camera-card-header-right">
          <LiveBadge isOnline={hasFrame && !!streamSrc} />
          <button
            type="button"
            className="camera-icon-btn"
            onClick={handleRetry}
            title="รีเฟรชสัญญาณกล้อง"
            aria-label="รีเฟรชสัญญาณกล้อง"
          >
            <IconRefresh size={15} />
          </button>
          <button
            type="button"
            className="camera-icon-btn"
            onClick={openExpanded}
            title="ขยายเต็มจอ"
            aria-label={`เปิดดูกล้อง ${name || ip} แบบขยาย`}
          >
            <IconMaximize size={15} />
          </button>
        </div>
      </div>

      {/* Interactive Feed Stage */}
      <button
        type="button"
        className="camera-card-feed"
        onClick={openExpanded}
        aria-label={`ขยายดูภาพจากกล้อง ${name || ip}`}
      >
        {streamSrc ? (
          <StreamImage
            key={streamSrc}
            src={streamSrc}
            alt={`ภาพสดจากกล้อง ${name || ip}`}
          />
        ) : (
          <div className="camera-card-placeholder">
            <div className="spinner" />
            <span className="camera-placeholder-title">กำลังเชื่อมต่ออุปกรณ์...</span>
          </div>
        )}
      </button>

      {/* Footer */}
      <div className="camera-card-footer">
        <StatusChip status={status} hasFrame={hasFrame} />
        <button type="button" className="camera-card-hint-btn" onClick={openExpanded}>
          แตะเพื่อขยายดูภาพใหญ่
        </button>
      </div>
    </motion.article>
  );
}
