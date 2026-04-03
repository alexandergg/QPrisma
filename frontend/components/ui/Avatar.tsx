import React, { memo, useMemo, useState } from 'react';

type AvatarSize = 'sm' | 'md' | 'lg' | 'xl';
type AvatarVariant = 'circle' | 'rounded';

interface AvatarProps {
  src?: string;
  fallback: string;
  size?: AvatarSize;
  variant?: AvatarVariant;
  alt?: string;
  className?: string;
}

const sizePx: Record<AvatarSize, number> = {
  sm: 28,
  md: 36,
  lg: 44,
  xl: 56,
};

const textSize: Record<AvatarSize, string> = {
  sm: 'text-xs',
  md: 'text-sm',
  lg: 'text-base',
  xl: 'text-lg',
};

const Avatar = memo(function Avatar({
  src,
  fallback,
  size = 'md',
  variant = 'circle',
  alt,
  className = '',
}: AvatarProps) {
  const [imgError, setImgError] = useState(false);
  const showImage = Boolean(src) && !imgError;

  const initials = useMemo(() => {
    const parts = fallback.trim().split(/\s+/);
    if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    return fallback.slice(0, 2).toUpperCase();
  }, [fallback]);

  const px = sizePx[size];
  const borderRadius =
    variant === 'circle' ? 'rounded-full' : 'rounded-[var(--radius-lg)]';

  return (
    <div
      className={`inline-flex items-center justify-center shrink-0 overflow-hidden bg-[var(--amber-3)] ${borderRadius} ${className}`}
      style={{ width: px, height: px }}
      aria-label={alt ?? fallback}
    >
      {showImage ? (
        <img
          src={src}
          alt={alt ?? fallback}
          onError={() => setImgError(true)}
          className="w-full h-full object-cover"
        />
      ) : (
        <span
          className={`font-semibold text-[var(--amber-11)] select-none leading-none ${textSize[size]}`}
        >
          {initials}
        </span>
      )}
    </div>
  );
});

Avatar.displayName = 'Avatar';

export { Avatar };
export type { AvatarProps, AvatarSize, AvatarVariant };
