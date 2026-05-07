'use client';

import React from 'react';
import {
  ChevronRight,
  LogOut,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { BrandLogo } from '@/components/branding/BrandLogo';
import type { MediaItem } from '@/lib/api';

interface StudioSidebarProps {
  mediaList: MediaItem[];
  /** If provided, show a "Back to Library" button instead of New Upload */
  showBackButton?: boolean;
  onBackToLibrary?: () => void;
  children?: React.ReactNode;
}

export function StudioSidebar({
  mediaList,
  showBackButton,
  onBackToLibrary,
  children,
}: StudioSidebarProps) {
  const router = useRouter();
  const { user, logout } = useAuth();

  return (
    <div className="w-72 bg-white/70 backdrop-blur-xl border-r border-gray-200/50 flex flex-col sticky top-0 h-screen shadow-xl shadow-gray-200/20">
      <div className="p-6 flex flex-col h-full">
        {/* Logo */}
        <BrandLogo variant="lockup" className="mb-8" />

        {showBackButton && (
          <button
            onClick={onBackToLibrary}
            className="w-full px-5 py-3.5 bg-gray-100 hover:bg-gray-200 rounded-xl transition-all text-sm font-semibold flex items-center gap-3 text-gray-700 mb-6 group"
          >
            <ChevronRight className="w-4 h-4 rotate-180 group-hover:-translate-x-1 transition-transform" />
            Back to Library
          </button>
        )}

        {/* Sidebar-specific content (navigation, recent uploads, etc.) */}
        {children}

        {/* Recent uploads list (for upload view) */}
        {showBackButton && (
          <div className="flex-1 overflow-y-auto space-y-1">
            <div className="px-3 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wider">Recent Uploads</div>
            {mediaList.slice(0, 5).map((item) => (
              <button
                key={item.id}
                onClick={() => router.push(`/video/${item.id}`)}
                className="w-full text-left px-3 py-2.5 hover:bg-indigo-50 rounded-lg transition-all group flex items-center gap-3"
              >
                <div className="w-2 h-2 rounded-full bg-gray-300 group-hover:bg-indigo-500 transition-colors"></div>
                <p className="text-sm font-medium truncate text-gray-600 group-hover:text-indigo-600 transition-colors">
                  {item.original_filename}
                </p>
              </button>
            ))}
          </div>
        )}

        {/* User Section */}
        <div className="mt-auto pt-6 border-t border-gray-200/50 space-y-3">
          <div className="flex items-center gap-3 px-2">
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-indigo-500/30">
              {user?.email?.substring(0, 2).toUpperCase() || 'U'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-gray-900 truncate">{user?.full_name || 'User'}</p>
              <p className="text-xs text-gray-500 truncate">{user?.email}</p>
            </div>
          </div>
          <button
            onClick={logout}
            className="w-full px-4 py-2.5 bg-gray-100 hover:bg-red-50 rounded-xl text-gray-600 hover:text-red-600 transition-all font-medium flex items-center justify-center gap-2 text-sm"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </div>
    </div>
  );
}
