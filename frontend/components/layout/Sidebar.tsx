'use client';

import React from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  Zap,
  Plus,
  Film,
  Library,
  Settings,
  LogOut,
  ChevronRight,
  Upload,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { staggerContainer, staggerItem } from '@/lib/animations';

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
    <aside className="w-72 bg-white/80 backdrop-blur-xl border-r border-gray-200/50 flex flex-col h-screen sticky top-0 shadow-xl shadow-gray-200/20">
      <div className="p-5 flex flex-col h-full">
        {/* Logo */}
        <div className="flex items-center gap-3 mb-6">
          <div className="bg-gradient-to-br from-amber-500 to-orange-600 w-10 h-10 rounded-xl flex items-center justify-center shadow-lg shadow-amber-500/30">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <span className="text-xl font-bold bg-gradient-to-r from-gray-900 to-gray-600 bg-clip-text text-transparent">
            QPrisma
          </span>
        </div>

        {/* New Chat Button */}
        <motion.button
          whileTap={{ scale: 0.97 }}
          transition={{ duration: 0.1 }}
          onClick={onNewChat}
          className="w-full px-4 py-3 bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white rounded-xl transition-colors font-semibold flex items-center justify-center gap-2 shadow-lg shadow-amber-500/30 mb-6"
        >
          <Plus className="w-5 h-5" />
          New Chat
        </motion.button>

        {/* Mode Selector */}
        <div className="mb-4">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 px-1">
            Chat Mode
          </p>
          <div className="bg-gray-100 rounded-xl p-1 flex gap-1">
            <button
              onClick={() => onModeChange('single')}
              className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                currentMode === 'single'
                  ? 'bg-white text-gray-900 shadow-md'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Film className="w-4 h-4" />
              Single Video
            </button>
            <button
              onClick={() => onModeChange('library')}
              className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                currentMode === 'library'
                  ? 'bg-white text-gray-900 shadow-md'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Library className="w-4 h-4" />
              Library
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-2 px-1">
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
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-1">
            Quick Links
          </p>
          <motion.button
            variants={staggerItem}
            onClick={() => router.push('/library')}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all ${
              pathname === '/library'
                ? 'bg-amber-50 border border-amber-200 text-amber-700'
                : 'hover:bg-gray-50 text-gray-600'
            }`}
          >
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${
              pathname === '/library'
                ? 'bg-amber-500 text-white'
                : 'bg-gray-100'
            }`}>
              <Library className="w-3.5 h-3.5" />
            </div>
            <div className="flex-1 text-left">
              <p className="text-sm font-medium">My Library</p>
            </div>
            <ChevronRight className="w-4 h-4 text-gray-400" />
          </motion.button>
          <motion.button
            variants={staggerItem}
            onClick={() => router.push('/upload')}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all ${
              pathname === '/upload'
                ? 'bg-amber-50 border border-amber-200 text-amber-700'
                : 'hover:bg-gray-50 text-gray-600'
            }`}
          >
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${
              pathname === '/upload'
                ? 'bg-amber-500 text-white'
                : 'bg-gray-100'
            }`}>
              <Upload className="w-3.5 h-3.5" />
            </div>
            <div className="flex-1 text-left">
              <p className="text-sm font-medium">Upload Video</p>
            </div>
            <ChevronRight className="w-4 h-4 text-gray-400" />
          </motion.button>
        </motion.div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* User Section */}
        <div className="mt-auto pt-4 border-t border-gray-200/50">
          <div className="flex items-center gap-3 px-2 mb-3">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center text-sm font-bold text-white shadow-lg shadow-amber-500/30">
              {user?.email?.substring(0, 2).toUpperCase() || 'U'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-gray-900 truncate">
                {user?.full_name || 'User'}
              </p>
              <p className="text-xs text-gray-500 truncate">{user?.email}</p>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => router.push('/settings')}
              className="flex-1 px-3 py-2.5 bg-gray-100 hover:bg-gray-200 rounded-xl text-gray-600 transition-all font-medium flex items-center justify-center gap-2 text-sm"
            >
              <Settings className="w-4 h-4" />
              Settings
            </button>
            <button
              onClick={handleLogout}
              className="flex-1 px-3 py-2.5 bg-gray-100 hover:bg-red-50 rounded-xl text-gray-600 hover:text-red-600 transition-all font-medium flex items-center justify-center gap-2 text-sm"
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
