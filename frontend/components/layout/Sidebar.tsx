'use client';

import React from 'react';
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
  GitCompare,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import ThemeToggle from '@/components/ui/ThemeToggle';

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

  const handleLogout = () => {
    logout();
    router.push('/auth');
  };

  return (
    <aside className="w-72 bg-[var(--surface)]/80 backdrop-blur-xl border-r border-[var(--border)] flex flex-col h-screen sticky top-0 shadow-[var(--shadow-xl)]">
      <div className="p-5 flex flex-col h-full">
        {/* Logo */}
        <div className="flex items-center gap-3 mb-6">
          <div className="bg-gradient-to-br from-indigo-500 to-purple-600 w-10 h-10 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-500/30">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <span className="text-xl font-bold text-[var(--foreground)]">
            QPrisma
          </span>
        </div>

        {/* New Chat Button */}
        <button
          onClick={onNewChat}
          className="w-full px-4 py-3 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl transition-all font-semibold flex items-center justify-center gap-2 shadow-lg shadow-indigo-500/30 mb-6"
        >
          <Plus className="w-5 h-5" />
          New Chat
        </button>

        {/* Mode Selector */}
        <div className="mb-4">
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
        <div className="mb-4 space-y-1">
          <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-wider mb-2 px-1">
            Quick Links
          </p>
          <button
            onClick={() => router.push('/library')}
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
            <div className="flex-1 text-left">
              <p className="text-sm font-medium">My Library</p>
            </div>
            <ChevronRight className="w-4 h-4 text-[var(--text-tertiary)]" />
          </button>
          <button
            onClick={() => router.push('/compare')}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all ${
              pathname === '/compare'
                ? 'bg-indigo-50 border border-indigo-200 text-indigo-700'
                : 'hover:bg-gray-50 text-gray-600'
            }`}
          >
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${
              pathname === '/compare'
                ? 'bg-indigo-500 text-white'
                : 'bg-gray-100'
            }`}>
              <GitCompare className="w-3.5 h-3.5" />
            </div>
            <div className="flex-1 text-left">
              <p className="text-sm font-medium">Compare</p>
            </div>
            <ChevronRight className="w-4 h-4 text-gray-400" />
          </button>
          <button
            onClick={() => router.push('/upload')}
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
            <div className="flex-1 text-left">
              <p className="text-sm font-medium">Upload Video</p>
            </div>
            <ChevronRight className="w-4 h-4 text-[var(--text-tertiary)]" />
          </button>
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* User Section */}
        <div className="mt-auto pt-4 border-t border-[var(--border)]">
          <div className="flex items-center gap-3 px-2 mb-3">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-sm font-bold text-white shadow-lg shadow-indigo-500/30">
              {user?.email?.substring(0, 2).toUpperCase() || 'U'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-[var(--foreground)] truncate">
                {user?.full_name || 'User'}
              </p>
              <p className="text-xs text-[var(--text-secondary)] truncate">{user?.email}</p>
            </div>
            <ThemeToggle />
          </div>

          <div className="flex gap-2">
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
  );
}
