import './LiveBadge.css';

export default function LiveBadge({ isOnline = true }) {
  return (
    <span className={`live-badge ${isOnline ? 'online' : 'offline'}`}>
      <span className="live-dot" />
      {isOnline ? 'LIVE' : 'OFFLINE'}
    </span>
  );
}
