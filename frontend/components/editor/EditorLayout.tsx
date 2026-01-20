'use client';

import React from 'react';
import { ArrowLeft, Settings, Film } from 'lucide-react';
import { useRouter } from 'next/navigation';

interface EditorLayoutProps {
  projectName?: string;
  children: React.ReactNode;
  videoPanel: React.ReactNode;
  onSettingsClick?: () => void;
}

/**
 * Editor Layout: 2-column layout for video editor
 * Left: Video + Clips list (40%)
 * Right: Chat-to-Edit (60%)
 */
export default function EditorLayout({
  projectName,
  children,
  videoPanel,
  onSettingsClick,
}: EditorLayoutProps) {
  const router = useRouter();

  return (
    <div className="flex flex-col h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 overflow-hidden">
      {/* Decorative Background */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl"></div>
        <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl"></div>
        <div className="absolute -bottom-40 right-1/3 w-80 h-80 bg-gradient-to-br from-purple-200/30 to-pink-200/30 rounded-full blur-3xl"></div>
      </div>

      {/* Header */}
      <header className="relative z-20 flex items-center justify-between px-4 py-3 bg-white/80 backdrop-blur-sm border-b border-gray-200">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push('/editor')}
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-600 hover:text-gray-900 transition-colors"
            title="Back to projects"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          
          <div className="flex items-center gap-2">
            <div className="p-2 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg">
              <Film className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="font-semibold text-gray-900">
                {projectName || 'Untitled Project'}
              </h1>
              <p className="text-xs text-gray-500">Chat-to-Edit</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {onSettingsClick && (
            <button
              onClick={onSettingsClick}
              className="p-2 hover:bg-gray-100 rounded-lg text-gray-600 hover:text-gray-900 transition-colors"
              title="Project settings"
            >
              <Settings className="w-5 h-5" />
            </button>
          )}
        </div>
      </header>

      {/* Main Content - 2 Columns */}
      <div className="relative z-10 flex-1 flex min-h-0 overflow-hidden">
        {/* Left Column: Video + Clips (40%) */}
        <div className="w-[40%] min-w-[400px] flex-shrink-0 flex flex-col bg-white border-r border-gray-200">
          {videoPanel}
        </div>

        {/* Right Column: Chat (60%) */}
        <main className="flex-1 flex flex-col min-w-0 bg-white/50">
          {children}
        </main>
      </div>
    </div>
  );
}
