import React, { forwardRef, memo } from 'react';
import { Spinner } from './Spinner';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  children: React.ReactNode;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-[var(--amber-8)] text-white hover:bg-[var(--amber-9)] focus-visible:ring-[var(--amber-6)]',
  secondary:
    'bg-[var(--surface)] text-[var(--foreground)] border border-[var(--border)] hover:bg-[var(--surface-elevated)] focus-visible:ring-[var(--amber-6)]',
  ghost:
    'bg-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)] focus-visible:ring-[var(--amber-6)]',
  danger:
    'bg-[var(--rose-8)] text-white hover:bg-[var(--rose-7)] focus-visible:ring-[var(--rose-7)]',
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-sm gap-1.5',
  md: 'px-4 py-2 text-sm gap-2',
  lg: 'px-6 py-3 text-base gap-2',
};

const Button = memo(
  forwardRef<HTMLButtonElement, ButtonProps>(function Button(
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      disabled,
      children,
      className = '',
      ...rest
    },
    ref,
  ) {
    const isDisabled = disabled || loading;
    return (
      <button
        ref={ref}
        disabled={isDisabled}
        className={`inline-flex items-center justify-center font-medium rounded-[var(--radius-md)] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
        {...rest}
      >
        {loading && <Spinner size="sm" className="shrink-0" />}
        {children}
      </button>
    );
  }),
);

Button.displayName = 'Button';

export { Button };
export type { ButtonProps, ButtonVariant, ButtonSize };
