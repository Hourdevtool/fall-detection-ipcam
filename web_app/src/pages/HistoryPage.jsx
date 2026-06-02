import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import FallEventCard from '../components/FallEventCard';
import { getFallEvents } from '../lib/api';
import './HistoryPage.css';

const FILTERS = [
  { label: 'วันนี้', value: 'today' },
  { label: 'เมื่อวาน', value: 'yesterday' },
  { label: '7 วัน', value: 'week' },
  { label: 'ทั้งหมด', value: 'all' },
];

function getDateRange(filter) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  switch (filter) {
    case 'today':
      return { dateFrom: formatDate(today) };
    case 'yesterday': {
      const yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);
      return { dateFrom: formatDate(yesterday), dateTo: formatDate(today) };
    }
    case 'week': {
      const weekAgo = new Date(today);
      weekAgo.setDate(weekAgo.getDate() - 7);
      return { dateFrom: formatDate(weekAgo) };
    }
    default:
      return {};
  }
}

function formatDate(date) {
  return date.toISOString().split('T')[0];
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

export default function HistoryPage() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeFilter, setActiveFilter] = useState('today');

  useEffect(() => {
    fetchEvents();
  }, [activeFilter]);

  async function fetchEvents() {
    setLoading(true);
    try {
      const range = getDateRange(activeFilter);
      const data = await getFallEvents({ ...range, limit: 100 });
      setEvents(data.events || []);
    } catch (err) {
      console.error('Error fetching fall events:', err);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }

  const grouped = groupByDate(events);

  return (
    <div className="page">
      {/* Header */}
      <div className="page-header">
        <h1 className="page-title">📋 ประวัติการล้ม</h1>
        <p className="page-subtitle">ดูเหตุการณ์การล้มที่ระบบตรวจพบ</p>
      </div>

      {/* Filter */}
      <div className="filter-bar">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            className={`filter-chip ${activeFilter === f.value ? 'active' : ''}`}
            onClick={() => setActiveFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Events List */}
      {loading ? (
        <div className="history-loading">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 120, borderRadius: 16, marginBottom: 16 }} />
          ))}
        </div>
      ) : events.length === 0 ? (
        <motion.div
          className="empty-state"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <div className="empty-state-icon">🎉</div>
          <div className="empty-state-title">ไม่มีเหตุการณ์</div>
          <div className="empty-state-text">
            ไม่พบการล้มในช่วงเวลาที่เลือก<br />นั่นเป็นข่าวดี!
          </div>
        </motion.div>
      ) : (
        <div className="history-list">
          <AnimatePresence>
            {Object.entries(grouped).map(([dateLabel, dateEvents]) => (
              <div key={dateLabel} className="history-date-group">
                <div className="history-date-label">{dateLabel}</div>
                {dateEvents.map((event, index) => (
                  <FallEventCard key={event.id} event={event} />
                ))}
              </div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
