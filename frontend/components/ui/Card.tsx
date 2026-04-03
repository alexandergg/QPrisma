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
    'bg-[var(--surface)] shadow-[var(--shadow-sm)] border border-[var(--sage-3)]',
  outlined:
    'border border-[var(--sage-4)]',
  elevated:
    'bg-[var(--surface)] shadow-[var(--shadow-xl)] border border-[var(--sage-2)]',
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
        <div className="px-6 py-4 border-b border-[var(--sage-3)]">{header}</div>
      )}
      <div className="px-6 py-4">{children}</div>
      {footer && (
        <div className="px-6 py-4 border-t border-[var(--sage-3)]">{footer}</div>
      )}
    </div>
  );
});

Card.displayName = 'Card';

export { Card };
export type { CardProps, CardVariant };
