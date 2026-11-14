import { useState } from 'react';
import { motion } from 'framer-motion';
import { IconClock, IconVideo, IconWifiOff, IconMaximize } from './Icons';
import './FallEventCard.css';

function EventSnapshot({ src, alt, onPreview }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div className="fall-event-snapshot-fallback">
        <IconWifiOff size={20} />
        <span>ไม่สามารถโหลดภาพบันทึกได้ (อุปกรณ์อาจออฟไลน์)</span>
      </div>
    );
  }

  return (
    <button
      type="button"
      className="fall-event-snapshot-btn"
      onClick={onPreview}
      aria-label={`ดูภาพขนาดใหญ่: ${alt}`}
    >
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onError={() => setFailed(true)}
      />
      <span className="fall-event-zoom-pill">
        <IconMaximize size={13} />
        <span>ขยายภาพ</span>
      </span>
    </button>
  );
}

export default function FallEventCard({ event, onPreview }) {
  const date = new Date(event.detected_at * 1000);
  const timeStr = date.toLocaleTimeString('th-TH', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  return (
    <motion.article
      className="fall-event-card glass-card"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28 }}
    >
      {/* Timeline indicator */}
      <div className="fall-event-timeline" aria-hidden="true">
        <div className="fall-event-dot" />
        <div className="fall-event-line" />
      </div>

      <div className="fall-event-content">
        {/* Header */}
        <div className="fall-event-header">
          <div className="fall-event-time-badge">
            <span className="fall-event-pulse-dot" />
            <span className="fall-event-time mono">{timeStr}</span>
          </div>
          <span className="fall-event-camera">
            <IconVideo size={14} />
            <span>{event.camera_name || event.camera_ip}</span>
          </span>
        </div>

        {/* Snapshot */}
        {event.snapshot_url && (
          <div className="fall-event-snapshot">
            <EventSnapshot
              key={event.snapshot_url}
              src={event.snapshot_url}
              alt={`ภาพเหตุการณ์ล้มจากกล้อง ${event.camera_name || event.camera_ip} เวลา ${timeStr}`}
              onPreview={() => onPreview?.(event)}
            />
          </div>
        )}

        {/* Details */}
        <div className="fall-event-details">
          {event.duration_seconds > 0 ? (
            <span className="fall-event-duration">
              <IconClock size={13} />
              <span className="tabular-nums">
                ตรวจพบใน {event.duration_seconds.toFixed(1)} วินาที
              </span>
            </span>
          ) : (
            <span className="fall-event-duration">บันทึกเหตุการณ์อัตโนมัติ</span>
          )}
          <span className="fall-event-ip mono">{event.camera_ip}</span>
        </div>
      </div>
    </motion.article>
  );
}
