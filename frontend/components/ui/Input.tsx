import React, { forwardRef, memo, useId } from 'react';

type InputVariant = 'default' | 'filled';
type InputSize = 'sm' | 'md' | 'lg';

interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'> {
  variant?: InputVariant;
  size?: InputSize;
  label?: string;
  error?: string;
  helperText?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const variantStyles: Record<InputVariant, string> = {
  default:
    'bg-[var(--surface)] border border-[var(--border)]',
  filled:
    'bg-[var(--surface-elevated)] border border-transparent',
};

const sizeStyles: Record<InputSize, string> = {
  sm: 'h-8 px-2.5 text-sm',
  md: 'h-10 px-3 text-sm',
  lg: 'h-12 px-4 text-base',
};

const iconSizeStyles: Record<InputSize, string> = {
  sm: 'pl-8',
  md: 'pl-9',
  lg: 'pl-11',
};

const rightIconSizeStyles: Record<InputSize, string> = {
  sm: 'pr-8',
  md: 'pr-9',
  lg: 'pr-11',
};

const Input = memo(
  forwardRef<HTMLInputElement, InputProps>(function Input(
    {
      variant = 'default',
      size = 'md',
      label,
      error,
      helperText,
      leftIcon,
      rightIcon,
      className = '',
      id: externalId,
      ...rest
    },
    ref,
  ) {
    const generatedId = useId();
    const inputId = externalId ?? generatedId;
    const hasError = Boolean(error);

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label
            htmlFor={inputId}
            className="text-sm font-medium text-[var(--foreground)]"
          >
            {label}
          </label>
        )}
        <div className="relative">
          {leftIcon && (
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] pointer-events-none">
              {leftIcon}
            </span>
          )}
          <input
            ref={ref}
            id={inputId}
            className={`w-full rounded-[var(--radius-md)] transition-colors placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed ${variantStyles[variant]} ${sizeStyles[size]} ${leftIcon ? iconSizeStyles[size] : ''} ${rightIcon ? rightIconSizeStyles[size] : ''} ${hasError ? 'border-[var(--rose-7)] focus:ring-[var(--rose-7)]' : 'focus:ring-[var(--amber-6)]'} ${className}`}
            aria-invalid={hasError || undefined}
            aria-describedby={
              error ? `${inputId}-error` : helperText ? `${inputId}-helper` : undefined
            }
            {...rest}
          />
          {rightIcon && (
            <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] pointer-events-none">
              {rightIcon}
            </span>
          )}
        </div>
        {error && (
          <p id={`${inputId}-error`} className="text-xs text-[var(--rose-8)]">
            {error}
          </p>
        )}
        {!error && helperText && (
          <p id={`${inputId}-helper`} className="text-xs text-[var(--text-tertiary)]">
            {helperText}
          </p>
        )}
      </div>
    );
  }),
);

Input.displayName = 'Input';

export { Input };
export type { InputProps, InputVariant, InputSize };
