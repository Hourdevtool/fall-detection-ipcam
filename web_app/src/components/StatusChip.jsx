import './StatusChip.css';

export default function StatusChip({ status }) {
  const isFall = status && status.includes('FALL');

  return (
    <span className={`status-chip ${isFall ? 'status-danger' : 'status-normal'}`}>
      <span className="status-chip-dot" />
      {isFall ? '⚠️ ตรวจพบการล้ม!' : '✅ ปกติ'}
    </span>
  );
}
