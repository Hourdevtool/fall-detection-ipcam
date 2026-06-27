import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useCameraFeed } from '../hooks/useCameraFeed';
import { useAuth } from '../contexts/AuthContext';
import CameraCard from '../components/CameraCard';
import './DashboardPage.css';

export default function DashboardPage() {
  const { user, logout, devices, activeDevice, selectDevice, removeDevice, updateDeviceName } = useAuth();
  const navigate = useNavigate();
  const { frames, cameras, loading, error } = useCameraFeed(1500, !!activeDevice);

  // Check pairing status on mount
  useEffect(() => {
    if (devices.length === 0) {
      navigate('/pair', { replace: true });
    }
  }, [devices, navigate]);

  const handleEditDeviceName = (e, dev) => {
    e.stopPropagation();
    const newName = prompt('กรุณาป้อนชื่ออุปกรณ์ใหม่:', dev.name);
    if (newName && newName.trim() !== '' && newName !== dev.name) {
      updateDeviceName(dev.id, newName.trim());
    }
  };

  if (devices.length === 0 || !activeDevice) {
    return (
      <div className="page" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
        <div className="spinner" />
      </div>
    );
  }

  const cameraEntries = Object.entries(frames);

  return (
    <div className="page">
      {/* Header */}
      <div className="dashboard-header">
        <div>
          <h1 className="page-title">🛡️ เครื่องประมวลผลภาพอัจฉริยะเพื่อตรวจจับและแจ้งเตือนการล้มของผู้สูงอายุภายในบ้านด้วยปัญญาประดิษฐ์ (AI) ผ่านระบบไลน์</h1>
          <p className="page-subtitle">
            {activeDevice ? `อุปกรณ์: ${activeDevice.name}` : 'กำลังค้นหากล้อง...'}
          </p>
        </div>
        <button className="dashboard-avatar" onClick={logout} title="ออกจากระบบ">
          {user?.picture ? (
            <img src={user.picture} alt={user.name} />
          ) : (
            <span>👤</span>
          )}
        </button>
      </div>

      {/* Device Selector */}
      <div className="device-selector-section">
        <h2 className="section-title">📍 อุปกรณ์ตรวจจับ</h2>
        <div className="device-list">
          {devices.map((dev) => (
            <div 
              key={dev.id} 
              className={`device-card glass-card ${activeDevice.id === dev.id ? 'active' : ''}`}
              onClick={() => selectDevice(dev)}
            >
              <div className="device-info">
                <span className="device-name">
                  🖥️ {dev.name}
                  <button 
                    className="device-edit-btn" 
                    onClick={(e) => handleEditDeviceName(e, dev)}
                    title="แก้ไขชื่ออุปกรณ์"
                    style={{ marginLeft: '8px', background: 'none', border: 'none', cursor: 'pointer', fontSize: '14px' }}
                  >
                    ✏️
                  </button>
                </span>
                <span className="device-ip">{dev.ip}</span>
              </div>
              <button 
                className="device-delete-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm(`คุณต้องการลบอุปกรณ์ "${dev.name}" ใช่หรือไม่?\n(รหัสเชื่อมต่อจะถูกรีเซ็ต ต้องดูรหัสใหม่ที่หน้าจอ Mini PC เพื่อเชื่อมต่ออีกครั้ง)`)) {
                    removeDevice(dev.id);
                  }
                }}
                title="ลบอุปกรณ์"
              >
                🗑️
              </button>
            </div>
          ))}
          
          {/* Add Device Button */}
          <div 
            className="device-card add-device-card glass-card"
            onClick={() => navigate('/pair')}
          >
            <span className="add-device-icon">➕</span>
            <span className="add-device-text">เพิ่มอุปกรณ์</span>
          </div>
        </div>
      </div>

      {/* Camera Grid header */}
      <h2 className="section-title" style={{ marginTop: 16 }}>📹 กล้องวงจรปิด ({cameras.length})</h2>

      {/* Camera Grid */}
      {loading && cameras.length === 0 ? (
        <div className="dashboard-loading">
          <div className="skeleton" style={{ height: 200, borderRadius: 16 }} />
          <div className="skeleton" style={{ height: 200, borderRadius: 16, marginTop: 16 }} />
        </div>
      ) : cameras.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📡</div>
          <div className="empty-state-title">ไม่พบกล้องของอุปกรณ์นี้</div>
          <div className="empty-state-text">
            ระบบกำลังสแกนหากล้องในเครือข่ายของ {activeDevice.name}<br />กรุณารอสักครู่...
          </div>
        </div>
      ) : (
        <motion.div className="camera-grid" layout>
          <AnimatePresence>
            {cameras.map((camera) => {
              const frame = frames[camera.ip];
              return (
                <CameraCard
                  key={camera.ip}
                  ip={camera.ip}
                  name={camera.name || camera.ip}
                  frame={frame}
                  status={null}
                />
              );
            })}
          </AnimatePresence>
        </motion.div>
      )}

      {error && (
        <div className="dashboard-error">
          ⚠️ ไม่สามารถเชื่อมต่อกับอุปกรณ์ได้ ({error})
        </div>
      )}
    </div>
  );
}

