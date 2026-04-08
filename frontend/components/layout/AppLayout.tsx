'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronLeft } from 'lucide-react';
import Sidebar, { ChatMode } from './Sidebar';
import VideoPanel from './VideoPanel';
import { useAuth } from '@/contexts/AuthContext';
import type { Scene, Chapter, TranscriptSegment } from '@/types';

interface VideoData {
  url?: string;
  title?: string;
  duration?: number;
  scenes?: Scene[];
  chapters?: Chapter[];
  transcript?: TranscriptSegment[];
}

interface AppLayoutProps {
  children: React.ReactNode;
  showVideoPanel?: boolean;
  videoData?: VideoData;
  currentTime?: number;
  onTimeUpdate?: (time: number) => void;
  onSeek?: (time: number) => void;
}

export default function AppLayout({
  children,
  showVideoPanel = false,
  videoData,
  currentTime = 0,
  onTimeUpdate,
  onSeek,
}: AppLayoutProps) {
  const router = useRouter();
  useAuth();
  const [currentMode, setCurrentMode] = useState<ChatMode>('single');
  const [isVideoPanelVisible, setIsVideoPanelVisible] = useState(showVideoPanel);
  const [panelWidth, setPanelWidth] = useState(420);
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const isResizingRef = useRef(false);

  // Sync video panel visibility with prop
  useEffect(() => {
    setIsVideoPanelVisible(showVideoPanel);
  }, [showVideoPanel]);

  // Load persisted panel width
  useEffect(() => {
    const saved = localStorage.getItem('qprisma-panel-width');
    if (saved) {
      const parsed = parseInt(saved, 10);
      if (!isNaN(parsed) && parsed >= 320) setPanelWidth(parsed);
    }
  }, []);

  // Resize handle drag logic
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizingRef.current = true;
    const startX = e.clientX;
    const startWidth = panelWidth;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isResizingRef.current) return;
      const delta = startX - moveEvent.clientX;
      const newWidth = Math.min(Math.max(startWidth + delta, 320), window.innerWidth * 0.6);
      setPanelWidth(newWidth);
    };

    const handleMouseUp = () => {
      isResizingRef.current = false;
      localStorage.setItem('qprisma-panel-width', String(Math.round(panelWidth)));
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [panelWidth]);

  const handleResizeDoubleClick = useCallback(() => {
    setPanelWidth(420);
    localStorage.setItem('qprisma-panel-width', '420');
  }, []);

  const handleNewChat = () => {
    router.push('/chat/new');
  };

  const handleModeChange = (mode: ChatMode) => {
    setCurrentMode(mode);
  };

  return (
    <div className="flex h-screen bg-[var(--background)] overflow-hidden">
      {/* Decorative Elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl dark:from-indigo-900/20 dark:to-purple-900/20"></div>
        <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl dark:from-blue-900/15 dark:to-cyan-900/15"></div>
        <div className="absolute -bottom-40 right-1/3 w-80 h-80 bg-gradient-to-br from-purple-200/30 to-pink-200/30 rounded-full blur-3xl dark:from-purple-900/15 dark:to-pink-900/15"></div>
      </div>

      {/* Sidebar */}
      <div className="relative z-10 flex-shrink-0">
        <Sidebar
          currentMode={currentMode}
          onModeChange={handleModeChange}
          onNewChat={handleNewChat}
          isCollapsed={isSidebarCollapsed}
          onToggleCollapse={() => setIsSidebarCollapsed(prev => !prev)}
        />
      </div>

      {/* Main Content Area */}
      <div className="relative z-10 flex-1 flex min-w-0">
        {/* Chat/Main Content */}
        <main className="flex-1 flex flex-col min-w-0">
          {children}
        </main>

        {/* Resize Handle (desktop only) */}
        {isVideoPanelVisible && !isPanelCollapsed && (
          <div
            onMouseDown={handleMouseDown}
            onDoubleClick={handleResizeDoubleClick}
            className="hidden md:flex w-1 hover:w-1.5 bg-transparent hover:bg-violet-300 cursor-col-resize flex-shrink-0 transition-all duration-150 group relative items-center justify-center"
          >
            <div className="absolute inset-y-0 -left-1 -right-1 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
              <div className="w-1 h-8 rounded-full bg-violet-400" />
            </div>
          </div>
        )}

        {/* Video Panel */}
        {isVideoPanelVisible && (
          <div
            className="flex-shrink-0 h-[40vh] md:h-screen border-t md:border-t-0 md:border-l border-[var(--border)] bg-[var(--surface)] md:transition-[width] md:duration-300 overflow-hidden"
            style={{ width: isPanelCollapsed ? 0 : panelWidth }}
          >
            <div style={{ width: panelWidth, minWidth: panelWidth }} className="h-full">
              <VideoPanel
                videoUrl={videoData?.url}
                videoTitle={videoData?.title}
                duration={videoData?.duration}
                scenes={videoData?.scenes}
                chapters={videoData?.chapters}
                transcript={videoData?.transcript}
                currentTime={currentTime}
                onTimeUpdate={onTimeUpdate}
                onSeek={onSeek}
                isVisible={true}
                onClose={() => setIsVideoPanelVisible(false)}
                onCollapse={() => setIsPanelCollapsed(true)}
              />
            </div>
          </div>
        )}

        {/* Collapsed panel expand tab */}
        {isVideoPanelVisible && isPanelCollapsed && (
          <button
            onClick={() => setIsPanelCollapsed(false)}
            className="absolute right-0 top-1/2 -translate-y-1/2 z-20 bg-[var(--surface)] border border-[var(--border)] rounded-l-lg p-2 shadow-md hover:bg-[var(--surface-elevated)] transition-colors"
            title="Expand video panel"
          >
            <ChevronLeft className="w-4 h-4 text-[var(--text-secondary)]" />
          </button>
        )}
      </div>
    </div>
  );
}

// Export a context provider for updating layout state from children
export interface AppLayoutContextType {
  setShowVideoPanel: (show: boolean) => void;
  setVideoData: (data: VideoData) => void;
  currentMode: ChatMode;
}

export const AppLayoutContext = React.createContext<AppLayoutContextType | undefined>(undefined);

export function useAppLayout() {
  const context = React.useContext(AppLayoutContext);
  if (!context) {
    throw new Error('useAppLayout must be used within AppLayoutProvider');
  }
  return context;
}
