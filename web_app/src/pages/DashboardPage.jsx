import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useCameraFeed } from '../hooks/useCameraFeed';
import { useAuth } from '../contexts/AuthContext';
import CameraCard from '../components/CameraCard';
import Modal from '../components/Modal';
import LiveBadge from '../components/LiveBadge';
import StatusChip from '../components/StatusChip';
import {
  IconMonitor,
  IconPlus,
  IconPencil,
  IconTrash,
  IconVideo,
  IconRefresh,
  IconAlert,
  IconWifiOff,
  IconShieldCheck,
} from '../components/Icons';
import './DashboardPage.css';

export default function DashboardPage() {
  const {
    devices,
    activeDevice,
    selectDevice,
    removeDevice,
    updateDeviceName,
    loading: authLoading,
  } = useAuth();
  const navigate = useNavigate();
  const { cameras, loading, error, refresh } = useCameraFeed(5000, !!activeDevice);

  const [refreshing, setRefreshing] = useState(false);
  const [renameTarget, setRenameTarget] = useState(null);
  const [renameValue, setRenameValue] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [expandedCamera, setExpandedCamera] = useState(null);
  const [modalStreamKey, setModalStreamKey] = useState(0);
  const [modalStreamError, setModalStreamError] = useState(false);

  useEffect(() => {
    if (!authLoading && devices.length === 0) {
      navigate('/pair', { replace: true });
    }
  }, [authLoading, devices, navigate]);

  async function handleManualRefresh() {
    setRefreshing(true);
    await refresh();
    setTimeout(() => setRefreshing(false), 350);
  }

  function openRenameModal(e, dev) {
    e.stopPropagation();
    setRenameTarget(dev);
    setRenameValue(dev.name);
  }

  function handleRenameSubmit(e) {
    e.preventDefault();
    const trimmed = renameValue.trim();
    if (renameTarget && trimmed && trimmed !== renameTarget.name) {
      updateDeviceName(renameTarget.id, trimmed);
    }
    setRenameTarget(null);
  }

  function openDeleteModal(e, dev) {
    e.stopPropagation();
    setDeleteTarget(dev);
  }

  async function handleConfirmDelete() {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    await removeDevice(id);
  }

  function handleOpenCamera(cam) {
    setModalStreamError(false);
    setModalStreamKey((k) => k + 1);
    setExpandedCamera(cam);
  }

  if (authLoading || devices.length === 0 || !activeDevice) {
    return (
      <div className="page page-center-loading">
        <div className="spinner" />
      </div>
    );
  }

  const activeHostLabel = activeDevice.ip
    ? activeDevice.ip.replace(/^https?:\/\//, '')
    : 'ยังไม่มีปลายทางเชื่อมต่อ';

  const activeCameraCount = cameras.filter((c) => c.has_frame).length;

  return (
    <div className="page">
      {/* Page Header */}
      <div className="page-header page-header-row">
        <div>
          <h1 className="page-title">ภาพสดจากกล้อง</h1>
          <p className="page-subtitle">
            กำลังติดตามอุปกรณ์ <strong className="text-strong">{activeDevice.name}</strong>
          </p>
        </div>
        <div className="dashboard-header-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={handleManualRefresh}
            disabled={refreshing}
          >
            <IconRefresh size={15} className={refreshing ? 'spin-slow' : ''} />
            <span>รีเฟรช</span>
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => navigate('/pair')}
          >
            <IconPlus size={15} />
            <span>เพิ่มอุปกรณ์</span>
          </button>
        </div>
      </div>

      {/* Status Summary Strip */}
      <section className="dashboard-stats" aria-label="สรุปสถานะระบบ">
        <div className="stat-tile glass-card">
          <div className="stat-icon-box accent">
            <IconMonitor size={18} />
          </div>
          <div className="stat-meta">
            <span className="stat-label">อุปกรณ์ที่ใช้งาน</span>
            <span className="stat-value">{activeDevice.name}</span>
          </div>
        </div>

        <div className="stat-tile glass-card">
          <div className="stat-icon-box teal">
            <IconVideo size={18} />
          </div>
          <div className="stat-meta">
            <span className="stat-label">กล้องที่เชื่อมต่อ</span>
            <span className="stat-value tabular-nums">
              {cameras.length} ตัว ({activeCameraCount} ออนไลน์)
            </span>
          </div>
        </div>

        <div className="stat-tile glass-card">
          <div className={`stat-icon-box ${error || !activeDevice.token ? 'warn' : 'teal'}`}>
            <IconShieldCheck size={18} />
          </div>
          <div className="stat-meta">
            <span className="stat-label">สถานะการเชื่อมต่อ</span>
            <span className="stat-value">
              {error ? 'ขาดการเชื่อมต่อ' : activeDevice.token ? 'พร้อมเฝ้าระวัง' : 'กำลังยืนยันสิทธิ์'}
            </span>
          </div>
        </div>
      </section>

      {/* Device Selector */}
      <section className="device-selector-section" aria-label="เลือกอุปกรณ์">
        <div className="section-header-row">
          <h2 className="section-title">
            <IconMonitor size={16} />
            <span>อุปกรณ์ตรวจจับ ({devices.length})</span>
          </h2>
        </div>

        <div className="device-list">
          {devices.map((dev) => {
            const isActive = activeDevice.id === dev.id;
            const host = dev.ip ? dev.ip.replace(/^https?:\/\//, '') : 'ไม่พบ URL';
            return (
              <div
                key={dev.id}
                className={`device-card glass-card ${isActive ? 'active' : ''}`}
              >
                <button
                  type="button"
                  className="device-card-select"
                  onClick={() => selectDevice(dev)}
                  aria-pressed={isActive}
                >
                  <div className="device-card-title-row">
                    <span className={`device-dot ${dev.token ? 'online' : 'warn'}`} />
                    <span className="device-name">{dev.name}</span>
                  </div>
                  <span className="device-ip mono" title={dev.ip}>
                    {host}
                  </span>
                </button>

                <div className="device-card-actions">
                  <button
                    type="button"
                    className="device-action-btn"
                    onClick={(e) => openRenameModal(e, dev)}
                    title="แก้ไขชื่ออุปกรณ์"
                    aria-label={`แก้ไขชื่อ ${dev.name}`}
                  >
                    <IconPencil size={15} />
                  </button>
                  <button
                    type="button"
                    className="device-action-btn danger"
                    onClick={(e) => openDeleteModal(e, dev)}
                    title="ลบอุปกรณ์"
                    aria-label={`ลบอุปกรณ์ ${dev.name}`}
                  >
                    <IconTrash size={15} />
                  </button>
                </div>
              </div>
            );
          })}

          <button
            type="button"
            className="device-card add-device-card"
            onClick={() => navigate('/pair')}
          >
            <IconPlus size={18} />
            <span className="add-device-text">เพิ่มอุปกรณ์ใหม่</span>
          </button>
        </div>
      </section>

      {/* Connection Error Banner */}
      {error && (
        <div className="dashboard-error" role="alert">
          <IconAlert size={18} />
          <div className="dashboard-error-text">
            <strong>ไม่สามารถติดต่อเครื่อง {activeDevice.name} ได้</strong>
            <span>กรุณาตรวจสอบว่าเครื่องเปิดโปรแกรมและเชื่อมต่ออินเทอร์เน็ตอยู่ ({error})</span>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={handleManualRefresh}>
            ลองใหม่
          </button>
        </div>
      )}

      {/* Camera Grid Section */}
      <section aria-label="รายการกล้องวงจรปิด">
        <div className="section-header-row">
          <h2 className="section-title">
            <IconVideo size={16} />
            <span>กล้องวงจรปิด ({cameras.length})</span>
          </h2>
          <span className="device-endpoint-tag mono">{activeHostLabel}</span>
        </div>

        {loading && cameras.length === 0 ? (
          <div className="camera-grid">
            {[1, 2].map((item) => (
              <div key={item} className="skeleton camera-skeleton" />
            ))}
          </div>
        ) : cameras.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon-box">
              <IconWifiOff size={26} />
            </div>
            <h3 className="empty-state-title">ยังไม่มีกล้องในอุปกรณ์นี้</h3>
            <p className="empty-state-text">
              ระบบกำลังสแกนหากล้อง ONVIF ในเครือข่ายของ {activeDevice.name} กรุณารอสักครู่หรือกดปุ่มรีเฟรชด้านบน
            </p>
          </div>
        ) : (
          <motion.div className="camera-grid" layout>
            <AnimatePresence>
              {cameras.map((camera) => (
                <CameraCard
                  key={camera.ip}
                  ip={camera.ip}
                  name={camera.name || camera.ip}
                  edgeUrl={activeDevice.ip}
                  hasFrame={camera.has_frame}
                  status={null}
                  onExpand={handleOpenCamera}
                />
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </section>

      {/* Rename Device Modal */}
      <Modal
        open={!!renameTarget}
        onClose={() => setRenameTarget(null)}
        title="เปลี่ยนชื่ออุปกรณ์"
        subtitle={renameTarget ? `แก้ไขชื่อแสดงผลของ "${renameTarget.name}"` : ''}
        maxWidth="420px"
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setRenameTarget(null)}>
              ยกเลิก
            </button>
            <button type="submit" form="rename-device-form" className="btn btn-primary">
              บันทึกชื่อ
            </button>
          </>
        }
      >
        <form id="rename-device-form" onSubmit={handleRenameSubmit}>
          <label htmlFor="rename-input" className="modal-field-label">
            ชื่ออุปกรณ์ / สถานที่
          </label>
          <input
            id="rename-input"
            type="text"
            className="input-field"
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            placeholder="เช่น บ้านคุณยาย"
            autoFocus
            required
          />
        </form>
      </Modal>

      {/* Delete Device Confirmation Modal */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="ยืนยันการลบอุปกรณ์"
        maxWidth="440px"
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setDeleteTarget(null)}>
              ยกเลิก
            </button>
            <button type="button" className="btn btn-danger" onClick={handleConfirmDelete}>
              ลบอุปกรณ์
            </button>
          </>
        }
      >
        <div className="delete-confirm-body">
          <div className="delete-confirm-icon">
            <IconAlert size={22} />
          </div>
          <p className="delete-confirm-text">
            คุณต้องการลบอุปกรณ์ <strong>“{deleteTarget?.name}”</strong> ออกจากบัญชีใช่หรือไม่?
          </p>
          <p className="delete-confirm-note">
            รหัสเชื่อมต่อเดิมจะถูกยกเลิก หากต้องการดูกล้องนี้อีกครั้งต้องนำรหัส 6 หลักใหม่จากหน้าจอเครื่องมาจับคู่
          </p>
        </div>
      </Modal>

      {/* Expanded Live Camera Modal */}
      <Modal
        open={!!expandedCamera}
        onClose={() => setExpandedCamera(null)}
        title={expandedCamera?.name || expandedCamera?.ip || 'ภาพสดจากกล้อง'}
        subtitle={expandedCamera?.ip}
        maxWidth="920px"
        footer={
          expandedCamera && (
            <div className="camera-modal-footer-bar">
              <div className="camera-modal-badges">
                <LiveBadge isOnline={expandedCamera.hasFrame && !modalStreamError} />
                <StatusChip status={expandedCamera.status} hasFrame={expandedCamera.hasFrame} />
              </div>
              <div className="camera-modal-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setModalStreamError(false);
                    setModalStreamKey((k) => k + 1);
                  }}
                >
                  <IconRefresh size={15} />
                  <span>เชื่อมต่อใหม่</span>
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => setExpandedCamera(null)}
                >
                  ปิดมุมมองขยาย
                </button>
              </div>
            </div>
          )
        }
      >
        {expandedCamera && (
          <div className="camera-modal-stage">
            {expandedCamera.edgeUrl && !modalStreamError ? (
              <img
                key={`${expandedCamera.ip}-${modalStreamKey}`}
                src={`${expandedCamera.edgeUrl}/api/stream/${expandedCamera.ip}?modal=${modalStreamKey}`}
                alt={`ภาพขยายกล้อง ${expandedCamera.name}`}
                className="camera-modal-img"
                onError={() => setModalStreamError(true)}
              />
            ) : (
              <div className="camera-modal-fallback">
                <IconWifiOff size={32} />
                <span>ไม่สามารถโหลดสตรีมภาพจากกล้องนี้ได้ในขณะนี้</span>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
