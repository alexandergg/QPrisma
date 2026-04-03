import React, { memo } from 'react';

type TooltipSide = 'top' | 'bottom' | 'left' | 'right';

interface TooltipProps {
  content: string;
  children: React.ReactNode;
  side?: TooltipSide;
  className?: string;
}

const sideStyles: Record<TooltipSide, string> = {
  top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
  left: 'right-full top-1/2 -translate-y-1/2 mr-1.5',
  right: 'left-full top-1/2 -translate-y-1/2 ml-1.5',
};

let tooltipIdCounter = 0;

const Tooltip = memo(function Tooltip({
  content,
  children,
  side = 'top',
  className = '',
}: TooltipProps) {
  const id = React.useId?.() ?? `tooltip-${++tooltipIdCounter}`;
  return (
    <span className={`group relative inline-flex ${className}`} aria-describedby={id}>
      {children}
      <span
        id={id}
        role="tooltip"
        className={`absolute ${sideStyles[side]} z-50 pointer-events-none whitespace-nowrap bg-[var(--foreground)] text-[var(--surface)] text-xs px-2 py-1 rounded-[var(--radius-sm)] opacity-0 invisible scale-95 transition-all duration-[var(--duration-fast)] group-hover:opacity-100 group-hover:visible group-hover:scale-100 group-focus-within:opacity-100 group-focus-within:visible group-focus-within:scale-100`}
      >
        {content}
      </span>
    </span>
  );
});

Tooltip.displayName = 'Tooltip';

export { Tooltip };
export type { TooltipProps, TooltipSide };
