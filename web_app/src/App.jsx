import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';

import ProtectedRoute from './components/ProtectedRoute';
import AppShell from './components/AppShell';

import LoginPage from './pages/LoginPage';
import PairPage from './pages/PairPage';
import DashboardPage from './pages/DashboardPage';
import HistoryPage from './pages/HistoryPage';

export default function App() {
  const location = useLocation();

  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        {/* Public */}
        <Route path="/login" element={<LoginPage />} />

        {/* Protected */}
        <Route
          path="/pair"
          element={
            <ProtectedRoute>
              <PairPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <AppShell>
                <DashboardPage />
              </AppShell>
            </ProtectedRoute>
          }
        />
        <Route
          path="/history"
          element={
            <ProtectedRoute>
              <AppShell>
                <HistoryPage />
              </AppShell>
            </ProtectedRoute>
          }
        />

        {/* Default redirect */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </AnimatePresence>
  );
}
