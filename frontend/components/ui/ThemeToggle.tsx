'use client';

import React, { memo, useEffect, useState } from 'react';
import { Sun, Moon } from 'lucide-react';

function getInitialTheme(): boolean {
  if (typeof window === 'undefined') return false;
  const stored = localStorage.getItem('qprisma-theme');
  if (stored === 'dark') return true;
  if (stored === 'light') return false;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
}

function ThemeToggle({ className = '' }: { className?: string }) {
  const [isDark, setIsDark] = useState(getInitialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
  }, [isDark]);

  const toggle = () => {
    const next = !isDark;
    setIsDark(next);
    if (next) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('qprisma-theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('qprisma-theme', 'light');
    }
  };

  return (
    <button
      onClick={toggle}
      className={`p-2 rounded-[var(--radius-lg)] transition-colors duration-[var(--duration-normal)]
        bg-[var(--surface-elevated)] hover:bg-[var(--border)]
        text-[var(--text-secondary)] hover:text-[var(--foreground)]
        ${className}`}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
    </button>
  );
}

ThemeToggle.displayName = 'ThemeToggle';
export default memo(ThemeToggle);
