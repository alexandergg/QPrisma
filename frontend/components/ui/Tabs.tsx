import React, { memo, useCallback, useRef, useEffect, useState } from 'react';

interface Tab {
  id: string;
  label: string;
  icon?: React.ReactNode;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onChange: (tabId: string) => void;
  className?: string;
}

const Tabs = memo(function Tabs({
  tabs,
  activeTab,
  onChange,
  className = '',
}: TabsProps) {
  const tabsRef = useRef<Map<string, HTMLButtonElement>>(new Map());
  const [underlineStyle, setUnderlineStyle] = useState<React.CSSProperties>({});

  const setTabRef = useCallback(
    (id: string) => (el: HTMLButtonElement | null) => {
      if (el) tabsRef.current.set(id, el);
      else tabsRef.current.delete(id);
    },
    [],
  );

  useEffect(() => {
    const el = tabsRef.current.get(activeTab);
    if (el) {
      setUnderlineStyle({
        width: el.offsetWidth,
        transform: `translateX(${el.offsetLeft}px)`,
      });
    }
  }, [activeTab, tabs]);

  return (
    <div className={`relative ${className}`} role="tablist">
      <div className="flex border-b border-[var(--border)]">
        {tabs.map((tab) => {
          const isActive = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              ref={setTabRef(tab.id)}
              role="tab"
              aria-selected={isActive}
              onClick={() => onChange(tab.id)}
              className={`inline-flex items-center gap-1.5 px-4 py-2.5 text-sm transition-colors whitespace-nowrap -mb-px ${
                isActive
                  ? 'font-semibold text-[var(--foreground)]'
                  : 'font-medium text-[var(--text-secondary)] hover:text-[var(--foreground)]'
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          );
        })}
      </div>
      <span
        className="absolute bottom-0 left-0 h-0.5 bg-[var(--amber-8)] transition-all duration-[var(--duration-normal)] ease-[var(--easing-default)]"
        style={underlineStyle}
      />
    </div>
  );
});

Tabs.displayName = 'Tabs';

export { Tabs };
export type { TabsProps, Tab };
