import { NavLink } from 'react-router-dom';
import { motion } from 'framer-motion';
import { IconVideo, IconHistory } from './Icons';
import './BottomNav.css';

const tabs = [
  { path: '/dashboard', icon: IconVideo, label: 'ภาพสด' },
  { path: '/history', icon: IconHistory, label: 'ประวัติการล้ม' },
];

export default function BottomNav() {
  return (
    <nav className="bottom-nav" aria-label="แถบนำทางมือถือ">
      <div className="bottom-nav-inner">
        {tabs.map((tab) => {
          const IconComponent = tab.icon;
          return (
            <NavLink
              key={tab.path}
              to={tab.path}
              className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
            >
              {({ isActive }) => (
                <>
                  <span className="nav-tab-icon">
                    <IconComponent size={20} />
                  </span>
                  <span className="nav-tab-label">{tab.label}</span>
                  {isActive && (
                    <motion.div
                      className="nav-tab-indicator"
                      layoutId="nav-indicator"
                      transition={{ type: 'spring', stiffness: 450, damping: 34 }}
                    />
                  )}
                </>
              )}
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}
