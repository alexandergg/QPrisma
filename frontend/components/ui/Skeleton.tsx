import React, { memo } from 'react';

type SkeletonVariant = 'text' | 'circular' | 'rectangular';

interface SkeletonProps {
  variant?: SkeletonVariant;
  width?: string | number;
  height?: string | number;
  className?: string;
}

const variantStyles: Record<SkeletonVariant, string> = {
  text: 'rounded-[var(--radius-sm)]',
  circular: 'rounded-full',
  rectangular: 'rounded-[var(--radius-md)]',
};

const defaultDimensions: Record<SkeletonVariant, { width?: string; height: string }> = {
  text: { width: '100%', height: '1em' },
  circular: { width: '40px', height: '40px' },
  rectangular: { width: '100%', height: '120px' },
};

const Skeleton = memo(function Skeleton({
  variant = 'text',
  width,
  height,
  className = '',
}: SkeletonProps) {
  const defaults = defaultDimensions[variant];

  return (
    <div
      aria-hidden="true"
      className={`bg-[var(--surface-elevated)] animate-pulse ${variantStyles[variant]} ${className}`}
      style={{
        width: width ?? defaults.width,
        height: height ?? defaults.height,
      }}
    />
  );
});

Skeleton.displayName = 'Skeleton';

export { Skeleton };
export type { SkeletonProps, SkeletonVariant };
