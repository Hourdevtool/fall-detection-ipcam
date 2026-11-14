import { useState, useRef, useEffect } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import ThemeToggle from './ThemeToggle';
import BottomNav from './BottomNav';
import {
  BrandLogo,
  IconVideo,
  IconHistory,
  IconPlus,
  IconLogOut,
  IconMonitor,
  IconUser,
} from './Icons';
import './AppShell.css';

export default function AppShell({ children }) {
  const { user, logout, activeDevice } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!menuOpen) return;
    const handleOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('touchstart', handleOutside);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('touchstart', handleOutside);
    };
  }, [menuOpen]);

  return (
    <div className="app-shell">
      {/* Desktop Sidebar (>= 960px) */}
      <aside className="app-sidebar" aria-label="เมนูหลัก">
        <div className="sidebar-brand">
          <BrandLogo size={34} />
          <div className="sidebar-brand-text">
            <span className="sidebar-brand-name">FallGuard AI</span>
            <span className="sidebar-brand-sub">ระบบเฝ้าระวังการล้มอัจฉริยะ</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          <NavLink
            to="/dashboard"
            className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          >
            <IconVideo size={19} />
            <span>ภาพสดจากกล้อง</span>
          </NavLink>

          <NavLink
            to="/history"
            className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          >
            <IconHistory size={19} />
            <span>ประวัติการล้ม</span>
          </NavLink>

          <button
            type="button"
            className="sidebar-link sidebar-link-action"
            onClick={() => navigate('/pair')}
          >
            <IconPlus size={19} />
            <span>เพิ่มอุปกรณ์ใหม่</span>
          </button>
        </nav>

        {activeDevice && (
          <div className="sidebar-device-pill">
            <div className="sidebar-device-label">
              <IconMonitor size={14} />
              <span>อุปกรณ์ที่กำลังดู</span>
            </div>
            <div className="sidebar-device-row">
              <span className={`status-dot-sm ${activeDevice.token ? 'online' : 'warn'}`} />
              <span className="sidebar-device-name">{activeDevice.name}</span>
            </div>
          </div>
        )}

        <div className="sidebar-footer">
          <ThemeToggle variant="segmented" />

          <div className="sidebar-user">
            <div className="user-avatar-sm">
              {user?.picture ? (
                <img src={user.picture} alt={user.name || 'ผู้ใช้งาน'} />
              ) : (
                <IconUser size={16} />
              )}
            </div>
            <div className="sidebar-user-meta">
              <span className="sidebar-user-name">{user?.name || 'ผู้ใช้งาน'}</span>
              <span className="sidebar-user-email">{user?.email || ''}</span>
            </div>
            <button
              type="button"
              className="sidebar-logout-btn"
              onClick={logout}
              title="ออกจากระบบ"
              aria-label="ออกจากระบบ"
            >
              <IconLogOut size={17} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Column */}
      <div className="app-workspace">
        {/* Mobile & Tablet Top Bar (< 960px) */}
        <header className="mobile-topbar">
          <div className="mobile-topbar-inner">
            <div className="mobile-brand">
              <BrandLogo size={28} />
              <div className="mobile-brand-text">
                <span className="mobile-brand-name">FallGuard AI</span>
                {activeDevice && (
                  <span className="mobile-brand-device">{activeDevice.name}</span>
                )}
              </div>
            </div>

            <div className="mobile-topbar-actions" ref={menuRef}>
              <ThemeToggle variant="icon" />

              <button
                type="button"
                className="mobile-avatar-btn"
                onClick={() => setMenuOpen((prev) => !prev)}
                aria-expanded={menuOpen}
                aria-label="เมนูบัญชีผู้ใช้"
              >
                {user?.picture ? (
                  <img src={user.picture} alt={user.name || 'ผู้ใช้งาน'} />
                ) : (
                  <IconUser size={18} />
                )}
              </button>

              {menuOpen && (
                <div className="mobile-user-menu" role="menu">
                  <div className="mobile-user-menu-header">
                    <span className="mobile-user-menu-name">{user?.name || 'ผู้ใช้งาน'}</span>
                    {user?.email && (
                      <span className="mobile-user-menu-email">{user.email}</span>
                    )}
                  </div>
                  <button
                    type="button"
                    className="mobile-user-menu-item"
                    onClick={() => {
                      setMenuOpen(false);
                      navigate('/pair');
                    }}
                    role="menuitem"
                  >
                    <IconPlus size={16} />
                    <span>เพิ่ม / จับคู่อุปกรณ์</span>
                  </button>
                  <button
                    type="button"
                    className="mobile-user-menu-item danger"
                    onClick={() => {
                      setMenuOpen(false);
                      logout();
                    }}
                    role="menuitem"
                  >
                    <IconLogOut size={16} />
                    <span>ออกจากระบบ</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="app-main">{children}</main>

        {/* Bottom Navigation for Mobile & Tablet */}
        <BottomNav />
      </div>
    </div>
  );
}
