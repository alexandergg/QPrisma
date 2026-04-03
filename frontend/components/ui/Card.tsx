import React, { memo } from 'react';

type CardVariant = 'default' | 'outlined' | 'elevated';

interface CardProps {
  variant?: CardVariant;
  header?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

const variantStyles: Record<CardVariant, string> = {
  default:
    'bg-[var(--surface)] shadow-[var(--shadow-sm)] border border-[var(--border)]',
  outlined:
    'border border-[var(--border)]',
  elevated:
    'bg-[var(--surface)] shadow-[var(--shadow-xl)] border border-[var(--border-subtle)]',
};

const Card = memo(function Card({
  variant = 'default',
  header,
  footer,
  children,
  className = '',
}: CardProps) {
  return (
    <div className={`rounded-2xl overflow-hidden ${variantStyles[variant]} ${className}`}>
      {header && (
        <div className="px-6 py-4 border-b border-[var(--border-subtle)]">{header}</div>
      )}
      <div className="px-6 py-4">{children}</div>
      {footer && (
        <div className="px-6 py-4 border-t border-[var(--border-subtle)]">{footer}</div>
      )}
    </div>
  );
});

Card.displayName = 'Card';

export { Card };
export type { CardProps, CardVariant };
