import React, { memo, useCallback, useEffect, useRef } from 'react';

type DialogSize = 'sm' | 'md' | 'lg' | 'xl';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: DialogSize;
}

const sizeStyles: Record<DialogSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
};

const Dialog = memo(function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  size = 'md',
}: DialogProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const handleOverlayClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === overlayRef.current) onClose();
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  // Lock body scroll when open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-[fadeIn_var(--duration-fast)_var(--easing-default)]"
    >
      <div
        ref={panelRef}
        className={`relative w-full ${sizeStyles[size]} mx-4 bg-[var(--surface)] rounded-[var(--radius-xl)] shadow-[var(--shadow-xl)] animate-[scaleIn_var(--duration-normal)_var(--easing-spring)]`}
      >
        {title && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
            <h2 className="text-lg font-semibold text-[var(--foreground)]">{title}</h2>
            <button
              onClick={onClose}
              aria-label="Close dialog"
              className="p-1 rounded-[var(--radius-sm)] text-[var(--text-tertiary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--foreground)] transition-colors"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M4 4l8 8M12 4l-8 8" />
              </svg>
            </button>
          </div>
        )}
        {!title && (
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="absolute top-3 right-3 p-1 rounded-[var(--radius-sm)] text-[var(--text-tertiary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--foreground)] transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        )}
        <div className="px-6 py-4">{children}</div>
        {footer && (
          <div className="px-6 py-4 border-t border-[var(--border-subtle)]">{footer}</div>
        )}
      </div>
    </div>
  );
});

Dialog.displayName = 'Dialog';

export { Dialog };
export type { DialogProps, DialogSize };
