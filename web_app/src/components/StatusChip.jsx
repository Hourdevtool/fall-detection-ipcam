import { IconAlert, IconCheckCircle } from './Icons';
import './StatusChip.css';

export default function StatusChip({ status, hasFrame = true }) {
  const isFall = status && status.includes('FALL');

  if (!hasFrame && !isFall) {
    return (
      <span className="status-chip status-standby">
        <span className="status-chip-dot" />
        รอสัญญาณภาพ
      </span>
    );
  }

  return (
    <span className={`status-chip ${isFall ? 'status-danger' : 'status-normal'}`}>
      {isFall ? <IconAlert size={13} /> : <IconCheckCircle size={13} />}
      {isFall ? 'ตรวจพบการล้ม' : 'ปกติ'}
    </span>
  );
}
