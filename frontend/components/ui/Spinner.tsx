import React, { memo } from 'react';

type SpinnerSize = 'sm' | 'md' | 'lg';

interface SpinnerProps {
  size?: SpinnerSize;
  className?: string;
}

const sizeMap: Record<SpinnerSize, number> = {
  sm: 16,
  md: 24,
  lg: 32,
};

const Spinner = memo(function Spinner({ size = 'md', className = '' }: SpinnerProps) {
  const px = sizeMap[size];
  return (
    <span role="status" className={`inline-flex ${className}`}>
      <svg
        className="animate-spin text-current"
        width={px}
        height={px}
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
        />
      </svg>
      <span className="sr-only">Loading…</span>
    </span>
  );
});

Spinner.displayName = 'Spinner';

export { Spinner };
export type { SpinnerProps, SpinnerSize };
