'use client';

import React, { useState, useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  Plus,
  Film,
  Library,
  Settings,
  LogOut,
  ChevronRight,
  Upload,
  GitCompare,
  Menu,
  X,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import ThemeToggle from '@/components/ui/ThemeToggle';
import { staggerContainer, staggerItem } from '@/lib/animations';
import { BrandLogo } from '@/components/branding/BrandLogo';

export type ChatMode = 'single' | 'library';

interface SidebarProps {
  currentMode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
  onNewChat: () => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

export default function Sidebar({
  currentMode,
  onModeChange,
  onNewChat,
  isCollapsed = false,
  onToggleCollapse,
}: SidebarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, logout } = useAuth();

  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    // Syncing with Next.js router — close mobile sidebar on navigation
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMobileOpen(false);
  }, [pathname]);

  const handleLogout = () => {
    logout();
    router.push('/auth');
  };

  return (
    <>
      {/* Mobile hamburger toggle */}
      <button
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-4 left-4 z-50 p-2.5 rounded-xl bg-[var(--surface)] shadow-md border border-[var(--border)]"
        aria-label="Open menu"
      >
        <Menu className="w-5 h-5 text-[var(--foreground)]" />
      </button>

      {/* Mobile backdrop overlay */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed md:sticky top-0 z-40 md:z-10 h-screen
          bg-[var(--surface)]/80 backdrop-blur-xl border-r border-[var(--border)]
          flex flex-col shadow-[var(--shadow-xl)] md:shadow-none
          transition-all duration-300
          ${isCollapsed ? 'w-72 md:w-16' : 'w-72'}
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
        `}
      >
        <div className={`flex flex-col h-full ${isCollapsed ? 'p-5 md:px-2 md:py-3' : 'p-5'}`}>
          {/* Mobile close button */}
          <button
            onClick={() => setMobileOpen(false)}
            className="md:hidden absolute top-4 right-4 p-2 rounded-xl hover:bg-[var(--surface-elevated)] text-[var(--text-secondary)]"
            aria-label="Close menu"
          >
            <X className="w-5 h-5" />
          </button>

          {/* Logo */}
          <div className={`mb-6 ${isCollapsed ? 'flex justify-center' : ''}`}>
            <BrandLogo
              variant={isCollapsed ? 'mark' : 'lockup'}
              className={isCollapsed ? 'mx-auto' : ''}
            />
          </div>

          {/* New Chat Button */}
          <motion.button
            whileTap={{ scale: 0.97 }}
            transition={{ duration: 0.1 }}
            onClick={() => { onNewChat(); setMobileOpen(false); }}
            className={`w-full px-4 py-3 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl transition-colors font-semibold flex items-center justify-center gap-2 shadow-lg shadow-indigo-500/30 mb-6 ${isCollapsed ? 'md:px-0' : ''}`}
            title="New Chat"
          >
            <Plus className="w-5 h-5 flex-shrink-0" />
            <span className={isCollapsed ? 'md:hidden' : ''}>New Chat</span>
          </motion.button>

          {/* Mode Selector */}
          <div className={`mb-4 ${isCollapsed ? 'md:hidden' : ''}`}>
            <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-3 px-1">
              Chat Mode
            </p>
            <div className="bg-[var(--surface-elevated)] rounded-xl p-1 flex gap-1">
              <button
                onClick={() => onModeChange('single')}
                className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                  currentMode === 'single'
                    ? 'bg-[var(--surface)] text-[var(--foreground)] shadow-[var(--shadow-md)]'
                    : 'text-[var(--text-secondary)] hover:text-[var(--foreground)]'
                }`}
              >
                <Film className="w-4 h-4" />
                Single Video
              </button>
              <button
                onClick={() => onModeChange('library')}
                className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                  currentMode === 'library'
                    ? 'bg-[var(--surface)] text-[var(--foreground)] shadow-[var(--shadow-md)]'
                    : 'text-[var(--text-secondary)] hover:text-[var(--foreground)]'
                }`}
              >
                <Library className="w-4 h-4" />
                Library
              </button>
            </div>
            <p className="text-xs text-[var(--text-tertiary)] mt-2 px-1">
              {currentMode === 'single'
                ? 'Chat with one video at a time'
                : 'Search across all your videos'}
            </p>
          </div>

          {/* Quick Links */}
          <motion.div
            variants={staggerContainer}
            initial="initial"
            animate="animate"
            className="mb-4 space-y-1"
          >
            <p className={`text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-2 px-1 ${isCollapsed ? 'md:hidden' : ''}`}>
              Quick Links
            </p>
            <motion.button
              variants={staggerItem}
              onClick={() => { router.push('/library'); setMobileOpen(false); }}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all ${
                pathname === '/library'
                  ? 'bg-indigo-50 border border-indigo-200 text-indigo-700 dark:bg-indigo-500/10 dark:border-indigo-500/30 dark:text-indigo-400'
                  : 'hover:bg-[var(--surface-elevated)] text-[var(--text-secondary)]'
              }`}
            >
              <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${
                pathname === '/library'
                  ? 'bg-indigo-500 text-white'
                  : 'bg-[var(--surface-elevated)]'
              }`}>
                <Library className="w-3.5 h-3.5" />
              </div>
              <div className={`flex-1 text-left ${isCollapsed ? 'md:hidden' : ''}`}>
                <p className="text-sm font-medium">My Library</p>
              </div>
              <ChevronRight className={`w-4 h-4 text-[var(--text-tertiary)] ${isCollapsed ? 'md:hidden' : ''}`} />
            </motion.button>
            <motion.button
              variants={staggerItem}
              onClick={() => { router.push('/compare'); setMobileOpen(false); }}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all ${
                pathname === '/compare'
                  ? 'bg-indigo-50 border border-indigo-200 text-indigo-700 dark:bg-indigo-500/10 dark:border-indigo-500/30 dark:text-indigo-400'
                  : 'hover:bg-[var(--surface-elevated)] text-[var(--text-secondary)]'
              }`}
            >
              <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${
                pathname === '/compare'
                  ? 'bg-indigo-500 text-white'
                  : 'bg-[var(--surface-elevated)]'
              }`}>
                <GitCompare className="w-3.5 h-3.5" />
              </div>
              <div className={`flex-1 text-left ${isCollapsed ? 'md:hidden' : ''}`}>
                <p className="text-sm font-medium">Compare</p>
              </div>
              <ChevronRight className={`w-4 h-4 text-[var(--text-tertiary)] ${isCollapsed ? 'md:hidden' : ''}`} />
            </motion.button>
            <motion.button
              variants={staggerItem}
              onClick={() => { router.push('/upload'); setMobileOpen(false); }}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all ${
                pathname === '/upload'
                  ? 'bg-indigo-50 border border-indigo-200 text-indigo-700 dark:bg-indigo-500/10 dark:border-indigo-500/30 dark:text-indigo-400'
                  : 'hover:bg-[var(--surface-elevated)] text-[var(--text-secondary)]'
              }`}
            >
              <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${
                pathname === '/upload'
                  ? 'bg-indigo-500 text-white'
                  : 'bg-[var(--surface-elevated)]'
              }`}>
                <Upload className="w-3.5 h-3.5" />
              </div>
              <div className={`flex-1 text-left ${isCollapsed ? 'md:hidden' : ''}`}>
                <p className="text-sm font-medium">Upload Video</p>
              </div>
              <ChevronRight className={`w-4 h-4 text-[var(--text-tertiary)] ${isCollapsed ? 'md:hidden' : ''}`} />
            </motion.button>
          </motion.div>

          {/* Spacer */}
          <div className="flex-1" />

          {/* Desktop collapse toggle */}
          {onToggleCollapse && (
            <button
              onClick={onToggleCollapse}
              className="hidden md:flex w-full items-center justify-center py-2 mb-2 rounded-xl hover:bg-[var(--surface-elevated)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <ChevronRight className={`w-4 h-4 transition-transform duration-200 ${isCollapsed ? '' : 'rotate-180'}`} />
            </button>
          )}

          {/* User Section */}
          <div className="mt-auto pt-4 border-t border-[var(--border)]">
            <div className={`flex items-center gap-3 px-2 mb-3 ${isCollapsed ? 'md:justify-center md:px-0' : ''}`}>
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-sm font-bold text-white shadow-lg shadow-indigo-500/30 flex-shrink-0">
                {user?.email?.substring(0, 2).toUpperCase() || 'U'}
              </div>
              <div className={`flex-1 min-w-0 ${isCollapsed ? 'md:hidden' : ''}`}>
                <p className="text-sm font-semibold text-[var(--foreground)] truncate">
                  {user?.full_name || 'User'}
                </p>
                <p className="text-xs text-[var(--text-secondary)] truncate">{user?.email}</p>
              </div>
              <div className={isCollapsed ? 'md:hidden' : ''}>
                <ThemeToggle />
              </div>
            </div>

            <div className={`flex gap-2 ${isCollapsed ? 'md:hidden' : ''}`}>
              <button
                onClick={() => router.push('/settings')}
                className="flex-1 px-3 py-2.5 bg-[var(--surface-elevated)] hover:bg-[var(--border)] rounded-xl text-[var(--text-secondary)] transition-all font-medium flex items-center justify-center gap-2 text-sm"
              >
                <Settings className="w-4 h-4" />
                Settings
              </button>
              <button
                onClick={handleLogout}
                className="flex-1 px-3 py-2.5 bg-[var(--surface-elevated)] hover:bg-red-50 rounded-xl text-[var(--text-secondary)] hover:text-red-600 transition-all font-medium flex items-center justify-center gap-2 text-sm dark:hover:bg-red-500/10"
              >
                <LogOut className="w-4 h-4" />
                Sign Out
              </button>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
