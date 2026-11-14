import { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { IconClose } from './Icons';
import './Modal.css';

export default function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  maxWidth = '480px',
}) {
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose?.();
      }
    };

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="modal-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          onClick={onClose}
          role="dialog"
          aria-modal="true"
          aria-label={title}
        >
          <motion.div
            className="modal-dialog"
            style={{ maxWidth }}
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ type: 'spring', stiffness: 360, damping: 30 }}
            onClick={(e) => e.stopPropagation()}
          >
            {(title || onClose) && (
              <div className="modal-header">
                <div className="modal-heading">
                  {title && <h2 className="modal-title">{title}</h2>}
                  {subtitle && <p className="modal-subtitle">{subtitle}</p>}
                </div>
                {onClose && (
                  <button
                    type="button"
                    className="modal-close-btn"
                    onClick={onClose}
                    aria-label="ปิดหน้าต่าง"
                  >
                    <IconClose size={18} />
                  </button>
                )}
              </div>
            )}

            <div className="modal-body">{children}</div>

            {footer && <div className="modal-footer">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
