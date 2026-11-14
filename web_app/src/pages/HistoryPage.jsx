import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import FallEventCard from '../components/FallEventCard';
import Modal from '../components/Modal';
import { getFallEvents } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import {
  IconHistory,
  IconRefresh,
  IconCheckCircle,
  IconWifiOff,
  IconAlert,
  IconClock,
} from '../components/Icons';
import './HistoryPage.css';

const FILTERS = [
  { label: 'วันนี้', value: 'today' },
  { label: 'เมื่อวาน', value: 'yesterday' },
  { label: '7 วันที่ผ่านมา', value: 'week' },
  { label: 'ทั้งหมด', value: 'all' },
];

function formatLocalDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getDateRange(filter) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  switch (filter) {
    case 'today':
      return { dateFrom: formatLocalDate(today) };
    case 'yesterday': {
      const yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);
      return { dateFrom: formatLocalDate(yesterday), dateTo: formatLocalDate(yesterday) };
    }
    case 'week': {
      const weekAgo = new Date(today);
      weekAgo.setDate(weekAgo.getDate() - 7);
      return { dateFrom: formatLocalDate(weekAgo) };
    }
    default:
      return {};
  }
}

function groupByDate(events) {
  const groups = {};
  for (const event of events) {
    const date = new Date(event.detected_at * 1000);
    const key = date.toLocaleDateString('th-TH', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
    if (!groups[key]) groups[key] = [];
    groups[key].push(event);
  }
  return groups;
}

async function fetchDeviceFallEvents(device, filter) {
  const range = getDateRange(filter);
  const data = await getFallEvents({ ...range, limit: 100, device });

  const deviceIp = device.ip.startsWith('http')
    ? device.ip
    : `http://${device.ip}`;

  return (data.events || []).map((event) => ({
    ...event,
    snapshot_url: event.snapshot_url ? `${deviceIp}${event.snapshot_url}` : null,
  }));
}

export default function HistoryPage() {
  const { activeDevice } = useAuth();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeFilter, setActiveFilter] = useState('today');
  const [selectedCamera, setSelectedCamera] = useState('all');
  const [previewEvent, setPreviewEvent] = useState(null);

  const loadEvents = useCallback(async (device, filter) => {
    setLoading(true);
    setError('');
    try {
      const mapped = await fetchDeviceFallEvents(device, filter);
      setEvents(mapped);
    } catch (err) {
      console.error('Error fetching fall events:', err);
      setEvents([]);
      setError(err.message || 'ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์เพื่อดึงข้อมูลได้');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!activeDevice) return;
    let cancelled = false;

    fetchDeviceFallEvents(activeDevice, activeFilter)
      .then((mapped) => {
        if (!cancelled) {
          setEvents(mapped);
          setError('');
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('Error fetching fall events:', err);
          setEvents([]);
          setError(err.message || 'ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์เพื่อดึงข้อมูลได้');
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeFilter, activeDevice]);

  const effectiveLoading = activeDevice ? loading : false;
  const effectiveError = activeDevice ? error : '';
  const effectiveEvents = useMemo(
    () => (activeDevice ? events : []),
    [activeDevice, events]
  );

  function handleFilterChange(nextFilter) {
    setSelectedCamera('all');
    if (activeDevice) {
      setLoading(true);
      setError('');
    }
    setActiveFilter(nextFilter);
  }

  function handleRefresh() {
    if (activeDevice) {
      loadEvents(activeDevice, activeFilter);
    }
  }

  const cameraOptions = useMemo(() => {
    const map = new Map();
    for (const ev of effectiveEvents) {
      const key = ev.camera_ip;
      const label = ev.camera_name || ev.camera_ip;
      if (key && !map.has(key)) {
        map.set(key, label);
      }
    }
    return Array.from(map.entries());
  }, [effectiveEvents]);

  const filteredEvents = useMemo(() => {
    if (selectedCamera === 'all') return effectiveEvents;
    return effectiveEvents.filter((ev) => ev.camera_ip === selectedCamera);
  }, [effectiveEvents, selectedCamera]);

  const grouped = useMemo(() => groupByDate(filteredEvents), [filteredEvents]);

  return (
    <div className="page">
      {/* Header */}
      <div className="page-header page-header-row">
        <div>
          <h1 className="page-title">ประวัติการตรวจพบการล้ม</h1>
          <p className="page-subtitle">
            {activeDevice
              ? `รายการแจ้งเตือนและภาพบันทึกจากอุปกรณ์ ${activeDevice.name}`
              : 'กรุณาจับคู่อุปกรณ์ก่อนเพื่อดูประวัติ'}
          </p>
        </div>

        {activeDevice && (
          <div className="history-header-actions">
            <span className="history-count-pill tabular-nums">
              <IconHistory size={15} />
              <span>พบ {filteredEvents.length} เหตุการณ์</span>
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={handleRefresh}
              disabled={effectiveLoading}
            >
              <IconRefresh size={15} className={effectiveLoading ? 'spin-slow' : ''} />
              <span>รีเฟรช</span>
            </button>
          </div>
        )}
      </div>

      {/* Filters Toolbar */}
      <div className="history-toolbar">
        <div className="filter-bar" role="group" aria-label="ตัวกรองช่วงเวลา">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              className={`filter-chip ${activeFilter === f.value ? 'active' : ''}`}
              onClick={() => handleFilterChange(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>

        {cameraOptions.length > 1 && (
          <div className="history-camera-filter">
            <label htmlFor="camera-filter-select" className="sr-only">
              กรองตามกล้อง
            </label>
            <select
              id="camera-filter-select"
              className="history-select"
              value={selectedCamera}
              onChange={(e) => setSelectedCamera(e.target.value)}
            >
              <option value="all">ทุกกล้อง ({effectiveEvents.length})</option>
              {cameraOptions.map(([ip, name]) => (
                <option key={ip} value={ip}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Events Content */}
      {!activeDevice ? (
        <div className="empty-state">
          <div className="empty-state-icon-box">
            <IconWifiOff size={26} />
          </div>
          <h2 className="empty-state-title">ยังไม่ได้เลือกอุปกรณ์</h2>
          <p className="empty-state-text">
            กรุณาจับคู่หรือเลือกอุปกรณ์ที่หน้าแรกก่อนเพื่อเรียกดูประวัติเหตุการณ์
          </p>
        </div>
      ) : effectiveLoading ? (
        <div className="history-grid">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton history-skeleton" />
          ))}
        </div>
      ) : effectiveError ? (
        <div className="empty-state">
          <div className="empty-state-icon-box danger">
            <IconAlert size={26} />
          </div>
          <h2 className="empty-state-title">ไม่สามารถโหลดประวัติได้</h2>
          <p className="empty-state-text">
            ไม่สามารถติดต่ออุปกรณ์ {activeDevice.name} ได้ในขณะนี้ ({effectiveError})
          </p>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            style={{ marginTop: 16 }}
            onClick={handleRefresh}
          >
            <IconRefresh size={15} />
            <span>ลองโหลดใหม่</span>
          </button>
        </div>
      ) : filteredEvents.length === 0 ? (
        <motion.div
          className="empty-state"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <div className="empty-state-icon-box success">
            <IconCheckCircle size={28} />
          </div>
          <h2 className="empty-state-title">ไม่พบเหตุการณ์การล้ม</h2>
          <p className="empty-state-text">
            ไม่พบการแจ้งเตือนการล้มในช่วงเวลาที่เลือก ทุกอย่างปลอดภัยดี
          </p>
        </motion.div>
      ) : (
        <div className="history-list">
          <AnimatePresence>
            {Object.entries(grouped).map(([dateLabel, dateEvents]) => (
              <section key={dateLabel} className="history-date-group">
                <div className="history-date-header">
                  <h2 className="history-date-label">{dateLabel}</h2>
                  <span className="history-date-count tabular-nums">
                    {dateEvents.length} เหตุการณ์
                  </span>
                </div>
                <div className="history-grid">
                  {dateEvents.map((event) => (
                    <FallEventCard
                      key={event.id}
                      event={event}
                      onPreview={setPreviewEvent}
                    />
                  ))}
                </div>
              </section>
            ))}
          </AnimatePresence>
        </div>
      )}

      {/* Snapshot Preview Lightbox */}
      <Modal
        open={!!previewEvent}
        onClose={() => setPreviewEvent(null)}
        title={previewEvent ? `ภาพเหตุการณ์ — ${previewEvent.camera_name || previewEvent.camera_ip}` : ''}
        subtitle={previewEvent?.detected_at_formatted}
        maxWidth="880px"
        footer={
          previewEvent && (
            <div className="snapshot-modal-footer">
              <div className="snapshot-modal-meta">
                {previewEvent.duration_seconds > 0 && (
                  <span className="snapshot-meta-chip">
                    <IconClock size={14} />
                    <span className="tabular-nums">
                      ตรวจพบใน {previewEvent.duration_seconds.toFixed(1)} วินาที
                    </span>
                  </span>
                )}
                <span className="snapshot-meta-ip mono">{previewEvent.camera_ip}</span>
              </div>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => setPreviewEvent(null)}
              >
                ปิดภาพ
              </button>
            </div>
          )
        }
      >
        {previewEvent?.snapshot_url && (
          <div className="snapshot-modal-stage">
            <img
              src={previewEvent.snapshot_url}
              alt={`ภาพเหตุการณ์ล้มจาก ${previewEvent.camera_name || previewEvent.camera_ip}`}
            />
          </div>
        )}
      </Modal>
    </div>
  );
}
