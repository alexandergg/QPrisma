import React, { memo } from 'react';

type ProgressVariant = 'default' | 'success' | 'warning' | 'error';
type ProgressSize = 'sm' | 'md';

interface ProgressBarProps {
  value: number;
  variant?: ProgressVariant;
  size?: ProgressSize;
  label?: string;
  showValue?: boolean;
  className?: string;
}

const fillStyles: Record<ProgressVariant, string> = {
  default: 'bg-[var(--violet-8)]',
  success: 'bg-[var(--sage-8)]',
  warning: 'bg-[var(--violet-6)]',
  error: 'bg-[var(--rose-8)]',
};

const sizeStyles: Record<ProgressSize, string> = {
  sm: 'h-1.5',
  md: 'h-2.5',
};

const ProgressBar = memo(function ProgressBar({
  value,
  variant = 'default',
  size = 'md',
  label,
  showValue = false,
  className = '',
}: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, value));

  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {(label || showValue) && (
        <div className="flex items-center justify-between text-sm">
          {label && (
            <span className="font-medium text-[var(--foreground)]">{label}</span>
          )}
          {showValue && (
            <span className="text-[var(--text-secondary)] tabular-nums">{Math.round(clamped)}%</span>
          )}
        </div>
      )}
      <div
        className={`w-full rounded-full bg-[var(--surface-elevated)] overflow-hidden ${sizeStyles[size]}`}
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div
          className={`h-full rounded-full transition-all duration-[var(--duration-slow)] ease-[var(--easing-default)] ${fillStyles[variant]}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
});

ProgressBar.displayName = 'ProgressBar';

export { ProgressBar };
export type { ProgressBarProps, ProgressVariant, ProgressSize };
