import { NavLink } from 'react-router-dom';
import { motion } from 'framer-motion';
import './BottomNav.css';

const tabs = [
  { path: '/dashboard', icon: '📹', label: 'Live' },
  { path: '/history', icon: '📋', label: 'ประวัติ' },
];

export default function BottomNav() {
  return (
    <nav className="bottom-nav">
      <div className="bottom-nav-inner">
        {tabs.map((tab) => (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
          >
            {({ isActive }) => (
              <>
                <span className="nav-tab-icon">{tab.icon}</span>
                <span className="nav-tab-label">{tab.label}</span>
                {isActive && (
                  <motion.div
                    className="nav-tab-indicator"
                    layoutId="nav-indicator"
                    transition={{ type: 'spring', stiffness: 500, damping: 35 }}
                  />
                )}
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
