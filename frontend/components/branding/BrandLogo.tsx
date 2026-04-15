'use client';

import Image from 'next/image';

type BrandLogoVariant = 'mark' | 'lockup' | 'full';
type BrandLogoTone = 'default' | 'inverse';
type BrandLogoTag = 'div' | 'span' | 'h1';

interface BrandLogoProps {
  as?: BrandLogoTag;
  className?: string;
  priority?: boolean;
  size?: number;
  tone?: BrandLogoTone;
  variant?: BrandLogoVariant;
}

const DEFAULT_MARK_SIZES: Record<BrandLogoVariant, number> = {
  mark: 48,
  lockup: 40,
  full: 72,
};

function joinClasses(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ');
}

export function BrandLogo({
  as = 'div',
  className,
  priority = false,
  size,
  tone = 'default',
  variant = 'lockup',
}: BrandLogoProps) {
  const Tag = as;
  const markSize = size ?? DEFAULT_MARK_SIZES[variant];
  const isInverse = tone === 'inverse';

  const containerClassName = joinClasses(
    'inline-flex items-center min-w-0',
    variant === 'full' ? 'gap-4 sm:gap-5' : 'gap-3',
    className,
  );

  const titleClassName = variant === 'full'
    ? joinClasses(
      'font-bold tracking-tight leading-none',
      'text-[1.25rem] sm:text-[1.8rem]',
      isInverse ? 'text-white' : 'text-[#29429A]',
    )
    : joinClasses(
      'text-xl font-bold leading-none',
      isInverse ? 'text-white' : 'text-[var(--foreground)]',
    );

  const subtitleClassName = joinClasses(
    'text-[0.62rem] sm:text-[0.78rem] font-medium uppercase tracking-[0.32em] mt-1',
    isInverse ? 'text-white/75' : 'text-[#4A62AE]',
  );

  return (
    <Tag className={containerClassName}>
      <Image
        src="/brand/qprisma-logo-mark.png"
        alt="QPrisma logo"
        width={markSize}
        height={markSize}
        priority={priority}
        className="h-auto shrink-0"
      />

      {variant !== 'mark' && (
        <span className="flex min-w-0 flex-col">
          <span className={titleClassName}>
            {variant === 'full' ? 'QPrisma: AI Video' : 'QPrisma'}
          </span>
          {variant === 'full' && (
            <span className={subtitleClassName}>
              Intelligence Accelerator
            </span>
          )}
        </span>
      )}
    </Tag>
  );
}
