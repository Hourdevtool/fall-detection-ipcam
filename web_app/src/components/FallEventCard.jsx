import { motion } from 'framer-motion';
import './FallEventCard.css';

export default function FallEventCard({ event }) {
  const date = new Date(event.detected_at * 1000);
  const timeStr = date.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  return (
    <motion.div
      className="fall-event-card glass-card"
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3 }}
    >
      {/* Timeline dot */}
      <div className="fall-event-timeline">
        <div className="fall-event-dot" />
        <div className="fall-event-line" />
      </div>

      <div className="fall-event-content">
        {/* Header */}
        <div className="fall-event-header">
          <span className="fall-event-time">🔴 {timeStr}</span>
          <span className="fall-event-camera">{event.camera_name || event.camera_ip}</span>
        </div>

        {/* Snapshot */}
        {event.snapshot_url && (
          <div className="fall-event-snapshot">
            <img
              src={event.snapshot_url}
              alt={`Fall detected at ${event.camera_name}`}
              loading="lazy"
            />
          </div>
        )}

        {/* Details */}
        <div className="fall-event-details">
          {event.duration_seconds > 0 && (
            <span className="fall-event-duration">
              ⏱ ตรวจพบใน {event.duration_seconds.toFixed(1)} วินาที
            </span>
          )}
          <span className="fall-event-ip">{event.camera_ip}</span>
        </div>
      </div>
    </motion.div>
  );
}
