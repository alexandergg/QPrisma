'use client';

import React, { useState, useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  Zap,
  Plus,
  Film,
  Library,
  Settings,
  LogOut,
  ChevronRight,
  Upload,
  Menu,
  X,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';

export type ChatMode = 'single' | 'library';

interface SidebarProps {
  currentMode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
  onNewChat: () => void;
}

export default function Sidebar({
  currentMode,
  onModeChange,
  onNewChat,
}: SidebarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, logout } = useAuth();

  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const handleLogout = () => {
    logout();
    router.push('/auth');
  };

  return (
    <>
      {/* Mobile hamburger toggle - visible below md */}
      <button
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-4 left-4 z-50 p-2.5 rounded-[var(--radius-lg)] bg-[var(--surface)] shadow-[var(--shadow-md)] border border-[var(--sage-3)]"
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
          bg-[var(--surface)]/90 backdrop-blur-xl border-r border-[var(--sage-3)]
          flex flex-col shadow-[var(--shadow-lg)] md:shadow-none
          transition-all duration-300 ease-[var(--ease-out-quint)]
          w-72
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
          md:w-16 lg:w-72
          md:hover:w-72 group/sidebar
        `}
      >
        <div className="p-5 md:p-2 lg:p-5 md:group-hover/sidebar:p-5 flex flex-col h-full transition-all duration-300">
          {/* Mobile close button */}
          <button
            onClick={() => setMobileOpen(false)}
            className="md:hidden absolute top-4 right-4 p-2 rounded-[var(--radius-lg)] hover:bg-[var(--sage-3)] text-[var(--sage-9)]"
            aria-label="Close menu"
          >
            <X className="w-5 h-5" />
          </button>

          {/* Logo */}
          <div className="flex items-center gap-3 mb-6">
            <div className="bg-gradient-to-br from-amber-9 to-amber-10 w-10 h-10 rounded-[var(--radius-xl)] flex items-center justify-center shadow-[var(--shadow-md)] flex-shrink-0">
              <Zap className="w-5 h-5 text-white" />
            </div>
            <span className="text-xl font-bold text-[var(--foreground)] md:hidden lg:inline md:group-hover/sidebar:inline truncate">
              QPrisma
            </span>
          </div>

          {/* New Chat Button */}
          <button
            onClick={() => { onNewChat(); setMobileOpen(false); }}
            className="w-full px-4 md:px-2 lg:px-4 md:group-hover/sidebar:px-4 py-3 bg-gradient-to-r from-amber-9 to-amber-10 hover:from-amber-10 hover:to-amber-11 text-white rounded-[var(--radius-xl)] transition-all font-semibold flex items-center justify-center gap-2 shadow-[var(--shadow-md)] mb-6"
          >
            <Plus className="w-5 h-5 flex-shrink-0" />
            <span className="md:hidden lg:inline md:group-hover/sidebar:inline">New Chat</span>
          </button>

          {/* Mode Selector */}
          <div className="mb-4 md:hidden lg:block md:group-hover/sidebar:block">
            <p className="text-xs font-semibold text-[var(--sage-8)] uppercase tracking-wider mb-3 px-1">
              Chat Mode
            </p>
            <div className="bg-[var(--sage-3)] rounded-[var(--radius-xl)] p-1 flex gap-1">
              <button
                onClick={() => onModeChange('single')}
                className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-[var(--radius-lg)] text-sm font-medium transition-all ${
                  currentMode === 'single'
                    ? 'bg-[var(--surface)] text-[var(--foreground)] shadow-[var(--shadow-sm)]'
                    : 'text-[var(--sage-9)] hover:text-[var(--sage-11)]'
                }`}
              >
                <Film className="w-4 h-4" />
                Single Video
              </button>
              <button
                onClick={() => onModeChange('library')}
                className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-[var(--radius-lg)] text-sm font-medium transition-all ${
                  currentMode === 'library'
                    ? 'bg-[var(--surface)] text-[var(--foreground)] shadow-[var(--shadow-sm)]'
                    : 'text-[var(--sage-9)] hover:text-[var(--sage-11)]'
                }`}
              >
                <Library className="w-4 h-4" />
                Library
              </button>
            </div>
            <p className="text-xs text-[var(--sage-8)] mt-2 px-1">
              {currentMode === 'single'
                ? 'Chat with one video at a time'
                : 'Search across all your videos'}
            </p>
          </div>

          {/* Quick Links */}
          <div className="mb-4 space-y-1">
            <p className="text-xs font-semibold text-[var(--sage-8)] uppercase tracking-wider mb-2 px-1 md:hidden lg:block md:group-hover/sidebar:block">
              Quick Links
            </p>
            <button
              onClick={() => { router.push('/library'); setMobileOpen(false); }}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-[var(--radius-xl)] transition-all ${
                pathname === '/library'
                  ? 'bg-amber-2 border border-amber-5 text-amber-11'
                  : 'hover:bg-[var(--sage-2)] text-[var(--sage-10)]'
              }`}
            >
              <div className={`w-7 h-7 rounded-[var(--radius-lg)] flex items-center justify-center flex-shrink-0 ${
                pathname === '/library'
                  ? 'bg-amber-9 text-white'
                  : 'bg-[var(--sage-3)]'
              }`}>
                <Library className="w-3.5 h-3.5" />
              </div>
              <div className="flex-1 text-left md:hidden lg:block md:group-hover/sidebar:block">
                <p className="text-sm font-medium">My Library</p>
              </div>
              <ChevronRight className="w-4 h-4 text-[var(--sage-7)] md:hidden lg:block md:group-hover/sidebar:block" />
            </button>
            <button
              onClick={() => { router.push('/upload'); setMobileOpen(false); }}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-[var(--radius-xl)] transition-all ${
                pathname === '/upload'
                  ? 'bg-amber-2 border border-amber-5 text-amber-11'
                  : 'hover:bg-[var(--sage-2)] text-[var(--sage-10)]'
              }`}
            >
              <div className={`w-7 h-7 rounded-[var(--radius-lg)] flex items-center justify-center flex-shrink-0 ${
                pathname === '/upload'
                  ? 'bg-amber-9 text-white'
                  : 'bg-[var(--sage-3)]'
              }`}>
                <Upload className="w-3.5 h-3.5" />
              </div>
              <div className="flex-1 text-left md:hidden lg:block md:group-hover/sidebar:block">
                <p className="text-sm font-medium">Upload Video</p>
              </div>
              <ChevronRight className="w-4 h-4 text-[var(--sage-7)] md:hidden lg:block md:group-hover/sidebar:block" />
            </button>
          </div>

          {/* Spacer */}
          <div className="flex-1" />

          {/* User Section */}
          <div className="mt-auto pt-4 border-t border-[var(--sage-3)]">
            <div className="flex items-center gap-3 px-2 mb-3">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-amber-9 to-amber-10 flex items-center justify-center text-sm font-bold text-white shadow-[var(--shadow-md)] flex-shrink-0">
                {user?.email?.substring(0, 2).toUpperCase() || 'U'}
              </div>
              <div className="flex-1 min-w-0 md:hidden lg:block md:group-hover/sidebar:block">
                <p className="text-sm font-semibold text-[var(--foreground)] truncate">
                  {user?.full_name || 'User'}
                </p>
                <p className="text-xs text-[var(--sage-8)] truncate">{user?.email}</p>
              </div>
            </div>

            <div className="flex gap-2 md:flex-col lg:flex-row md:group-hover/sidebar:flex-row">
              <button
                onClick={() => router.push('/settings')}
                className="flex-1 px-3 md:px-2 lg:px-3 md:group-hover/sidebar:px-3 py-2.5 bg-[var(--sage-2)] hover:bg-[var(--sage-3)] rounded-[var(--radius-xl)] text-[var(--sage-10)] transition-all font-medium flex items-center justify-center gap-2 text-sm"
              >
                <Settings className="w-4 h-4 flex-shrink-0" />
                <span className="md:hidden lg:inline md:group-hover/sidebar:inline">Settings</span>
              </button>
              <button
                onClick={handleLogout}
                className="flex-1 px-3 md:px-2 lg:px-3 md:group-hover/sidebar:px-3 py-2.5 bg-[var(--sage-2)] hover:bg-rose-3 rounded-[var(--radius-xl)] text-[var(--sage-10)] hover:text-rose-9 transition-all font-medium flex items-center justify-center gap-2 text-sm"
              >
                <LogOut className="w-4 h-4 flex-shrink-0" />
                <span className="md:hidden lg:inline md:group-hover/sidebar:inline">Sign Out</span>
              </button>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
