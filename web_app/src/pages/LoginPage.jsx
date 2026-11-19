import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { GoogleLogin } from '@react-oauth/google';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../hooks/useTheme';
import ThemeToggle from '../components/ThemeToggle';
import Modal from '../components/Modal';
import {
  BrandLogo,
  IconVideo,
  IconBell,
  IconShieldCheck,
  IconAlert,
  IconCheckCircle,
} from '../components/Icons';
import './LoginPage.css';

const HIGHLIGHTS = [
  {
    icon: IconVideo,
    title: 'เฝ้าระวังภาพสดจากกล้อง AI',
    desc: 'ติดตามกล้อง IP Camera ภายในบ้านแบบเรียลไทม์ทั้งบนคอมพิวเตอร์และมือถือ',
  },
  {
    icon: IconBell,
    title: 'แจ้งเตือนทันทีผ่านระบบ LINE',
    desc: 'ส่งภาพและเวลาเหตุการณ์การล้มไปยังกลุ่มอัตโนมัติพร้อมประวัติย้อนหลัง',
  },
  {
    icon: IconShieldCheck,
    title: 'ประมวลผลบน Edge Server ส่วนตัว',
    desc: 'วิเคราะห์ท่าทางผู้สูงอายุด้วย AI ในบ้านเพื่อความเป็นส่วนตัวและความแม่นยำสูง',
  },
];

export default function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const { theme, isDark } = useTheme();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [showTermsModal, setShowTermsModal] = useState(false);

  const isGoogleConfigured = !!import.meta.env.VITE_GOOGLE_CLIENT_ID;

  async function handleGoogleSuccess(tokenResponse) {
    if (!agreeTerms) {
      setError('กรุณากดยินยอมข้อกำหนดและเงื่อนไขการใช้งานก่อนเข้าสู่ระบบ');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const googleCredential = tokenResponse.access_token || tokenResponse.credential;
      await login(googleCredential);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError('เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่อีกครั้ง');
      console.error('Login error:', err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  if (isAuthenticated) {
    return null;
  }

  return (
    <div className="login-page">
      <div className="login-bg-mesh" aria-hidden="true" />

      {/* Top Bar */}
      <header className="login-topbar">
        <div className="login-topbar-brand">
          <BrandLogo size={32} />
          <span className="login-topbar-name">FallGuard AI</span>
        </div>
        <ThemeToggle variant="segmented" />
      </header>

      {/* Main Split Container */}
      <main className="login-main">
        <motion.section
          className="login-hero"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        >
          <span className="login-badge">AI Elderly Fall Detection</span>
          <h1 className="login-title">
            เฝ้าระวังการล้มผู้สูงอายุภายในบ้านอย่างอุ่นใจ
          </h1>
          <p className="login-subtitle">
            เครื่องประมวลผลภาพอัจฉริยะเพื่อตรวจจับและแจ้งเตือนการล้มของผู้สูงอายุภายในบ้านด้วยปัญญาประดิษฐ์ (AI) ผ่านระบบไลน์
          </p>

          <div className="login-highlights">
            {HIGHLIGHTS.map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.title} className="login-highlight-item">
                  <div className="login-highlight-icon">
                    <Icon size={18} />
                  </div>
                  <div>
                    <h2 className="login-highlight-title">{item.title}</h2>
                    <p className="login-highlight-desc">{item.desc}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </motion.section>

        <motion.section
          className="login-card glass-card"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="login-card-logo">
            <BrandLogo size={48} />
          </div>
          <h2 className="login-card-heading">เข้าสู่ระบบ</h2>
          <p className="login-card-desc">
            ลงชื่อเข้าใช้ด้วยบัญชี Google เพื่อเชื่อมต่อกับเครื่องตรวจจับและดูภาพจากกล้อง
          </p>

          <div className="login-terms-group">
            <label className="login-terms-label">
              <input
                type="checkbox"
                className="login-terms-checkbox"
                checked={agreeTerms}
                onChange={(e) => {
                  setAgreeTerms(e.target.checked);
                  if (error) setError('');
                }}
              />
              <span className="login-terms-text">
                ฉันได้อ่านและยินยอมตาม{' '}
                <button
                  type="button"
                  className="login-terms-link"
                  onClick={() => setShowTermsModal(true)}
                >
                  ข้อกำหนดและเงื่อนไขการใช้งาน (Terms of Service)
                </button>{' '}
                รวมถึงยินยอมให้ระบบถ่ายทอดและประมวลผลภาพจากกล้องเพื่อความปลอดภัย
              </span>
            </label>
          </div>

          <div className="login-actions">
            {!agreeTerms && (
              <p className="login-terms-notice">
                * โปรดทำเครื่องหมายยินยอมข้อกำหนดการใช้ภาพด้านบนก่อนดำเนินการเข้าสู่ระบบ
              </p>
            )}

            {isGoogleConfigured ? (
              <div
                className={`login-google-wrap ${loading ? 'is-loading' : ''} ${
                  !agreeTerms ? 'is-disabled' : ''
                }`}
                onClickCapture={(e) => {
                  if (!agreeTerms) {
                    e.stopPropagation();
                    setError('กรุณากดยินยอมข้อกำหนดและเงื่อนไขการใช้งานก่อนเข้าสู่ระบบ');
                  }
                }}
              >
                <GoogleLogin
                  key={`${theme}-${agreeTerms}`}
                  onSuccess={handleGoogleSuccess}
                  onError={() => setError('การยืนยันตัวตนผ่าน Google ล้มเหลว กรุณาลองใหม่')}
                  useOneTap={agreeTerms}
                  theme={isDark ? 'filled_black' : 'outline'}
                  shape="pill"
                  size="large"
                />
                {loading && (
                  <div className="login-loading-inline">
                    <div className="spinner" style={{ width: 18, height: 18, borderWidth: 2 }} />
                    <span>กำลังเข้าสู่ระบบ...</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="login-config-warning">
                <IconAlert size={18} />
                <span>ยังไม่ได้ตั้งค่า Google Client ID ในไฟล์สภาพแวดล้อม</span>
              </div>
            )}
          </div>

          {error && (
            <div className="login-error" role="alert">
              <IconAlert size={16} />
              <span>{error}</span>
            </div>
          )}

          <div className="login-card-footer">
            <span>รองรับการใช้งานบนคอมพิวเตอร์และสมาร์ตโฟน</span>
            <span className="mono">v1.0</span>
          </div>
        </motion.section>
      </main>

      {/* Terms of Service Modal */}
      <Modal
        open={showTermsModal}
        onClose={() => setShowTermsModal(false)}
        title="ข้อกำหนดและเงื่อนไขการใช้งาน (Terms of Service)"
        subtitle="นโยบายความเป็นส่วนตัวและการยินยอมการประมวลผลข้อมูลภาพ"
        maxWidth="620px"
        footer={
          <div className="terms-modal-footer">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setAgreeTerms(true);
                setError('');
                setShowTermsModal(false);
              }}
            >
              <IconCheckCircle size={16} />
              <span>ยินยอมและยอมรับข้อกำหนด</span>
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setShowTermsModal(false)}
            >
              ปิดหน้าต่าง
            </button>
          </div>
        }
      >
        <div className="terms-modal-content">
          <section className="terms-section">
            <h3 className="terms-title">1. วัตถุประสงค์ของการใช้งาน</h3>
            <p>
              ระบบ FallGuard AI เป็นระบบเฝ้าระวังและตรวจจับการล้มของผู้สูงอายุภายในบ้านด้วยปัญญาประดิษฐ์ (AI)
              โดยมุ่งเน้นเพื่อความปลอดภัยและการแจ้งเตือนเหตุฉุกเฉินในครอบครัวเท่านั้น
            </p>
          </section>

          <section className="terms-section">
            <h3 className="terms-title">2. การยินยอมการถ่ายทอดและประมวลผลข้อมูลภาพ</h3>
            <p>
              ในการเข้าใช้งานเว็บแอปพลิเคชันนี้ ท่านยินยอมให้ระบบเข้าถึง ถ่ายทอดสัญญาณสตรีมวิดีโอสด (Live Video Stream)
              และบันทึกภาพนิ่ง (Snapshot) จากกล้องวงจรปิดที่เชื่อมต่อกับเครื่อง เพื่อใช้ในการวิเคราะห์ท่าทางและส่งการแจ้งเตือน
            </p>
          </section>

          <section className="terms-section">
            <h3 className="terms-title">3. ความปลอดภัยและความเป็นส่วนตัวของข้อมูล</h3>
            <p>
              - การประมวลผลภาพด้วยโมเดล AI ดำเนินการบนเครื่องภายในเครือข่ายของท่านเอง (Edge Processing)<br />
              - ภาพถ่ายเหตุการณ์จะถูกจัดเก็บบนเครื่องและส่งตรงไปยังช่องทางแจ้งเตือนของท่านโดยไม่มีการนำภาพไปเผยแพร่ต่อบุคคลภายนอก<br />
              - ท่านมีสิทธิ์ในการลบ ปิดการเชื่อมต่อ หรือยกเลิกการจับคู่อุปกรณ์ได้ตลอดเวลาผ่านระบบจัดการอุปกรณ์
            </p>
          </section>

          <section className="terms-section">
            <h3 className="terms-title">4. การยืนยันความยินยอม</h3>
            <p>
              การทำเครื่องหมายในช่องยินยอมถือว่าท่านในฐานะผู้ครอบครองสถานที่หรือผู้ได้รับอนุญาต
              ได้อ่าน เข้าใจ และตกลงปฏิบัติตามข้อกำหนดและเงื่อนไขการใช้งานเหล่านี้โดยสมบูรณ์
            </p>
          </section>
        </div>
      </Modal>
    </div>
  );
}
