'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Sidebar, { ChatMode } from './Sidebar';
import VideoPanel from './VideoPanel';
import { useAuth } from '@/contexts/AuthContext';
import { apiClient } from '@/lib/api';

interface Conversation {
  id: string;
  title: string;
  videoId?: string;
  videoName?: string;
  lastMessage?: string;
  updatedAt: Date;
  mode: ChatMode;
}

interface VideoData {
  url?: string;
  title?: string;
  duration?: number;
  scenes?: any[];
  chapters?: any[];
  transcript?: any[];
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
  const { user, isAuthenticated } = useAuth();
  const [currentMode, setCurrentMode] = useState<ChatMode>('single');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | undefined>();
  const [isVideoPanelVisible, setIsVideoPanelVisible] = useState(showVideoPanel);

  // Load conversations from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem('qprisma_conversations');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        setConversations(
          parsed.map((c: any) => ({
            ...c,
            updatedAt: new Date(c.updatedAt),
          }))
        );
      } catch (e) {
        console.error('Failed to parse conversations:', e);
      }
    }
  }, []);

  // Save conversations to localStorage when they change
  useEffect(() => {
    if (conversations.length > 0) {
      localStorage.setItem('qprisma_conversations', JSON.stringify(conversations));
    }
  }, [conversations]);

  // Sync video panel visibility with prop
  useEffect(() => {
    setIsVideoPanelVisible(showVideoPanel);
  }, [showVideoPanel]);

  const handleNewChat = () => {
    router.push('/chat/new');
  };

  const handleSelectConversation = (id: string) => {
    setActiveConversationId(id);
    router.push(`/chat/${id}`);
  };

  const handleDeleteConversation = (id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeConversationId === id) {
      setActiveConversationId(undefined);
      router.push('/');
    }
  };

  const handleModeChange = (mode: ChatMode) => {
    setCurrentMode(mode);
    // If switching to library mode, might want to redirect or update UI
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 overflow-hidden">
      {/* Decorative Elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl"></div>
        <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl"></div>
        <div className="absolute -bottom-40 right-1/3 w-80 h-80 bg-gradient-to-br from-purple-200/30 to-pink-200/30 rounded-full blur-3xl"></div>
      </div>

      {/* Sidebar */}
      <div className="relative z-10 flex-shrink-0">
        <Sidebar
          conversations={conversations}
          activeConversationId={activeConversationId}
          currentMode={currentMode}
          onModeChange={handleModeChange}
          onNewChat={handleNewChat}
          onSelectConversation={handleSelectConversation}
          onDeleteConversation={handleDeleteConversation}
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
          <div className="w-[40%] min-w-[400px] max-w-[600px] flex-shrink-0 h-screen border-l border-gray-200 bg-white">
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
  setActiveConversation: (id: string, title: string, videoId?: string, videoName?: string) => void;
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
