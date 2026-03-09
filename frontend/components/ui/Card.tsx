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
    'bg-white shadow-sm border border-gray-200 dark:bg-gray-900 dark:border-gray-700',
  outlined:
    'border border-gray-200 dark:border-gray-700',
  elevated:
    'bg-white shadow-xl border border-gray-100 dark:bg-gray-900 dark:border-gray-700',
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
        <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-700">{header}</div>
      )}
      <div className="px-6 py-4">{children}</div>
      {footer && (
        <div className="px-6 py-4 border-t border-gray-100 dark:border-gray-700">{footer}</div>
      )}
    </div>
  );
});

Card.displayName = 'Card';

export { Card };
export type { CardProps, CardVariant };
