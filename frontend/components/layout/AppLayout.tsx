'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Sidebar, { ChatMode } from './Sidebar';
import VideoPanel from './VideoPanel';
import { useAuth } from '@/contexts/AuthContext';

interface Scene {
  scene_id: number;
  start_time: number;
  end_time: number;
  duration?: number;
  summary?: string;
}

interface Chapter {
  chapter_id: number;
  title: string;
  start_time: number;
  end_time: number;
  duration?: number;
  scene_ids?: number[];
}

interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  text: string;
}

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

  // Sync video panel visibility with prop
  useEffect(() => {
    setIsVideoPanelVisible(showVideoPanel);
  }, [showVideoPanel]);

  const handleNewChat = () => {
    router.push('/chat/new');
  };

  const handleModeChange = (mode: ChatMode) => {
    setCurrentMode(mode);
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-[var(--background)] via-[var(--surface)] to-amber-1 overflow-hidden">
      {/* Decorative Elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-amber-3/40 to-amber-4/40 rounded-full blur-3xl"></div>
        <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-[var(--sage-3)]/30 to-[var(--sage-4)]/30 rounded-full blur-3xl"></div>
        <div className="absolute -bottom-40 right-1/3 w-80 h-80 bg-gradient-to-br from-amber-2/30 to-[var(--sage-3)]/30 rounded-full blur-3xl"></div>
      </div>

      {/* Sidebar */}
      <div className="relative z-10 flex-shrink-0">
        <Sidebar
          currentMode={currentMode}
          onModeChange={handleModeChange}
          onNewChat={handleNewChat}
        />
      </div>

      {/* Main Content Area */}
      <div className="relative z-10 flex-1 flex min-w-0">
        {/* Chat/Main Content */}
        <main
          className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${
            isVideoPanelVisible ? 'w-[60%]' : 'w-full'
          }`}
        >
          {children}
        </main>

        {/* Video Panel (conditionally rendered) */}
        {isVideoPanelVisible && (
          <div className="w-full md:w-[40%] md:min-w-[400px] md:max-w-[600px] flex-shrink-0 h-[40vh] md:h-screen border-t md:border-t-0 md:border-l border-[var(--sage-3)] bg-[var(--surface)]">
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
            />
          </div>
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
