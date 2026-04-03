import React, { memo } from 'react';

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

const EmptyState = memo(function EmptyState({
  icon,
  title,
  description,
  action,
  className = '',
}: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center text-center py-16 ${className}`}>
      {icon && (
        <div className="mb-4 text-[var(--sage-6)]">{icon}</div>
      )}
      <h3 className="text-lg font-semibold text-[var(--foreground)]">{title}</h3>
      {description && (
        <p className="mt-1 text-sm text-[var(--sage-9)] max-w-sm">{description}</p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
});

EmptyState.displayName = 'EmptyState';

export { EmptyState };
export type { EmptyStateProps };
