import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';

import ProtectedRoute from './components/ProtectedRoute';
import BottomNav from './components/BottomNav';

import LoginPage from './pages/LoginPage';
import PairPage from './pages/PairPage';
import DashboardPage from './pages/DashboardPage';
import HistoryPage from './pages/HistoryPage';

import { useAuth } from './contexts/AuthContext';

// Pages that show the bottom navigation
const NAV_PAGES = ['/dashboard', '/history'];

export default function App() {
  const location = useLocation();
  const { isAuthenticated } = useAuth();
  const showNav = isAuthenticated && NAV_PAGES.includes(location.pathname);

  return (
    <>
      <AnimatePresence mode="wait">
        <Routes location={location} key={location.pathname}>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />

          {/* Protected */}
          <Route path="/pair" element={
            <ProtectedRoute><PairPage /></ProtectedRoute>
          } />
          <Route path="/dashboard" element={
            <ProtectedRoute><DashboardPage /></ProtectedRoute>
          } />
          <Route path="/history" element={
            <ProtectedRoute><HistoryPage /></ProtectedRoute>
          } />

          {/* Default redirect */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </AnimatePresence>

      {/* Bottom Navigation — only on main pages */}
      {showNav && <BottomNav />}
    </>
  );
}
