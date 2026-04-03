import React, { memo } from 'react';

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral';
type BadgeSize = 'sm' | 'md';

interface BadgeProps {
  variant?: BadgeVariant;
  size?: BadgeSize;
  children: React.ReactNode;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  success: 'bg-[var(--sage-2)] text-[var(--sage-8)]',
  warning: 'bg-[var(--amber-2)] text-[var(--amber-8)]',
  error: 'bg-[var(--rose-3)] text-[var(--rose-8)]',
  info: 'bg-[var(--blue-3)] text-[var(--blue-8)]',
  neutral: 'bg-[var(--surface-elevated)] text-[var(--text-secondary)]',
};

const sizeStyles: Record<BadgeSize, string> = {
  sm: 'px-1.5 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-xs font-medium',
};

const Badge = memo(function Badge({
  variant = 'neutral',
  size = 'md',
  children,
  className = '',
}: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full leading-tight ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
    >
      {children}
    </span>
  );
});

Badge.displayName = 'Badge';

export { Badge };
export type { BadgeProps, BadgeVariant, BadgeSize };
