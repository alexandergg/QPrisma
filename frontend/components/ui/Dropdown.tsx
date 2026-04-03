import React, { memo, useCallback, useEffect, useRef, useState } from 'react';

type DropdownAlign = 'left' | 'right';

interface DropdownItem {
  label: string;
  icon?: React.ReactNode;
  onClick: () => void;
  variant?: 'default' | 'danger';
}

interface DropdownProps {
  trigger: React.ReactNode;
  items: DropdownItem[];
  align?: DropdownAlign;
  className?: string;
}

const alignStyles: Record<DropdownAlign, string> = {
  left: 'left-0',
  right: 'right-0',
};

const Dropdown = memo(function Dropdown({
  trigger,
  items,
  align = 'left',
  className = '',
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const toggle = useCallback(() => setOpen((prev) => !prev), []);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        close();
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open, close]);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, close]);

  return (
    <div ref={containerRef} className={`relative inline-block ${className}`}>
      <button type="button" onClick={toggle} aria-haspopup="true" aria-expanded={open}>
        {trigger}
      </button>
      {open && (
        <div
          role="menu"
          className={`absolute ${alignStyles[align]} z-40 mt-1 min-w-[160px] bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-lg)] shadow-[var(--shadow-lg)] py-1 animate-[fadeIn_var(--duration-fast)_var(--easing-default)]`}
        >
          {items.map((item, i) => {
            const isDanger = item.variant === 'danger';
            return (
              <button
                key={i}
                role="menuitem"
                onClick={() => {
                  item.onClick();
                  close();
                }}
                className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left transition-colors ${
                  isDanger
                    ? 'text-[var(--rose-8)] hover:bg-[var(--rose-3)]'
                    : 'text-[var(--foreground)] hover:bg-[var(--surface-elevated)]'
                }`}
              >
                {item.icon}
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
});

Dropdown.displayName = 'Dropdown';

export { Dropdown };
export type { DropdownProps, DropdownItem, DropdownAlign };
