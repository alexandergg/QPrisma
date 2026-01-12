'use client';

import React, { useState, useEffect, use } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar, VideoPanel } from '@/components/layout';
import { ChatContainer } from '@/components/chat';
import { useAuth } from '@/contexts/AuthContext';
import { apiClient } from '@/lib/api';
import RequireAuth from '@/components/RequireAuth';
import { X, Film, Loader2 } from 'lucide-react';

interface VideoData {
  id: string;
  url?: string;
  title?: string;
  duration?: number;
  scenes?: any[];
  chapters?: any[];
  transcript?: any[];
}

interface ChatPageProps {
  params: Promise<{ id: string }>;
}

export default function ChatPage({ params }: ChatPageProps) {
  const resolvedParams = use(params);
  const router = useRouter();
  const { user } = useAuth();

  const [currentMode, setCurrentMode] = useState<'single' | 'library'>('single');
  const [selectedVideo, setSelectedVideo] = useState<VideoData | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  // Load conversation and associated video
  useEffect(() => {
    loadConversation();
  }, [resolvedParams.id]);

  const loadConversation = async () => {
    try {
      setIsLoading(true);

      // Load conversation from localStorage or API
      const savedConversations = localStorage.getItem('qprisma_conversations');
      if (savedConversations) {
        const conversations = JSON.parse(savedConversations);
        const conversation = conversations.find((c: any) => c.id === resolvedParams.id);

        if (conversation?.videoId) {
          await loadVideo(conversation.videoId);
        }
      }
    } catch (error) {
      console.error('Failed to load conversation:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const loadVideo = async (videoId: string) => {
    try {
      const [metadata, structure] = await Promise.all([
        apiClient.getVideoMetadata(videoId),
        apiClient.getVideoStructure(videoId).catch(() => null),
      ]);

      setSelectedVideo({
        id: videoId,
        url: metadata.blob_url,
        title: metadata.original_filename,
        duration: metadata.duration,
        scenes: structure?.scenes || [],
        chapters: structure?.chapters || [],
        transcript: metadata.audio_data?.transcription?.segments || [],
      });
    } catch (error) {
      console.error('Failed to load video:', error);
    }
  };

  const handleTimestampClick = (timestamp: number) => {
    setCurrentTime(timestamp);
  };

  if (isLoading) {
    return (
      <RequireAuth>
        <div className="flex items-center justify-center h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30">
          <div className="text-center">
            <Loader2 className="w-8 h-8 text-indigo-500 animate-spin mx-auto mb-3" />
            <p className="text-gray-500">Loading conversation...</p>
          </div>
        </div>
      </RequireAuth>
    );
  }

  return (
    <RequireAuth>
      <div className="flex h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 overflow-hidden">
        {/* Decorative Elements */}
        <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
          <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl"></div>
          <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl"></div>
        </div>

        {/* Sidebar */}
        <div className="relative z-10 flex-shrink-0">
          <Sidebar
            conversations={[]}
            activeConversationId={resolvedParams.id}
            currentMode={currentMode}
            onModeChange={setCurrentMode}
            onNewChat={() => router.push('/chat/new')}
            onSelectConversation={(id) => router.push(`/chat/${id}`)}
          />
        </div>

        {/* Main Content */}
        <div className="relative z-10 flex-1 flex min-w-0">
          {/* Chat Area */}
          <main
            className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${
              selectedVideo && currentMode === 'single' ? 'w-[60%]' : 'w-full'
            }`}
          >
            {/* Video Selection Bar */}
            {selectedVideo && currentMode === 'single' && (
              <div className="flex items-center gap-3 px-4 py-3 bg-white/80 backdrop-blur-sm border-b border-gray-100">
                <div className="flex items-center gap-2 px-3 py-1.5 bg-indigo-50 text-indigo-700 rounded-full">
                  <Film className="w-4 h-4" />
                  <span className="text-sm font-medium truncate max-w-[200px]">
                    {selectedVideo.title}
                  </span>
                </div>
              </div>
            )}

            {/* Chat Container */}
            <ChatContainer
              videoId={selectedVideo?.id}
              videoName={selectedVideo?.title}
              videoUrl={selectedVideo?.url}
              mode={currentMode}
              onTimestampClick={handleTimestampClick}
              userName={user?.full_name || user?.email}
            />
          </main>

          {/* Video Panel */}
          {selectedVideo && currentMode === 'single' && (
            <div className="w-[40%] min-w-[400px] max-w-[600px] flex-shrink-0 h-screen">
              <VideoPanel
                videoUrl={selectedVideo.url}
                videoTitle={selectedVideo.title}
                duration={selectedVideo.duration}
                scenes={selectedVideo.scenes}
                chapters={selectedVideo.chapters}
                transcript={selectedVideo.transcript}
                currentTime={currentTime}
                onTimeUpdate={setCurrentTime}
                onSeek={setCurrentTime}
                isVisible={true}
              />
            </div>
          )}
        </div>
      </div>
    </RequireAuth>
  );
}
