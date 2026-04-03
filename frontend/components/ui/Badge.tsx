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
  success: 'bg-emerald-50 text-emerald-800',
  warning: 'bg-amber-2 text-amber-11',
  error: 'bg-rose-3 text-rose-11',
  info: 'bg-blue-3 text-blue-11',
  neutral: 'bg-[var(--sage-3)] text-[var(--sage-11)]',
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
