import { useTheme } from '../hooks/useTheme';
import { IconSun, IconMoon } from './Icons';
import './ThemeToggle.css';

export default function ThemeToggle({ variant = 'segmented', className = '' }) {
  const { theme, setTheme, toggleTheme, isDark } = useTheme();

  if (variant === 'icon') {
    return (
      <button
        type="button"
        className={`theme-toggle-icon ${className}`}
        onClick={toggleTheme}
        aria-label={isDark ? 'เปลี่ยนเป็นโหมดสว่าง' : 'เปลี่ยนเป็นโหมดมืด'}
        title={isDark ? 'เปลี่ยนเป็นโหมดสว่าง' : 'เปลี่ยนเป็นโหมดมืด'}
      >
        {isDark ? <IconSun size={18} /> : <IconMoon size={18} />}
      </button>
    );
  }

  return (
    <div
      className={`theme-toggle-segmented ${className}`}
      role="group"
      aria-label="เลือกโหมดสีหน้าจอ"
    >
      <button
        type="button"
        className={`theme-segment-btn ${theme === 'light' ? 'active' : ''}`}
        onClick={() => setTheme('light')}
        aria-pressed={theme === 'light'}
      >
        <IconSun size={15} />
        <span>สว่าง</span>
      </button>
      <button
        type="button"
        className={`theme-segment-btn ${theme === 'dark' ? 'active' : ''}`}
        onClick={() => setTheme('dark')}
        aria-pressed={theme === 'dark'}
      >
        <IconMoon size={15} />
        <span>มืด</span>
      </button>
    </div>
  );
}
