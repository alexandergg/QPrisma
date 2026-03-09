'use client';

import React, { useState, useEffect, use, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar, VideoPanel } from '@/components/layout';
import { ChatContainer, type ChatMessageData } from '@/components/chat';
import { useAuth } from '@/contexts/AuthContext';
import { apiClient } from '@/lib/api';
import {
  type ConversationSummary,
  getConversationById,
  getConversationPreview,
  getConversationTitle,
  loadConversationMessages,
  loadConversations,
  removeConversation,
  saveConversationMessages,
  upsertConversation,
} from '@/lib/conversations';
import RequireAuth from '@/components/RequireAuth';
import { Film, Loader2 } from 'lucide-react';
import type { VideoData } from '../types';

interface ChatPageProps {
  params: Promise<{ id: string }>;
}

export default function ChatPage({ params }: ChatPageProps) {
  const resolvedParams = use(params);
  const router = useRouter();
  const { user } = useAuth();

  const [currentMode, setCurrentMode] = useState<'single' | 'library'>('single');
  const [selectedVideo, setSelectedVideo] = useState<VideoData | null>(null);
  const [selectedVideos, setSelectedVideos] = useState<VideoData[]>([]);
  const [currentTime, setCurrentTime] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessageData[]>([]);
  const [chatSessionId, setChatSessionId] = useState<string | undefined>();

  const isMultiVideo = selectedVideos.length > 1;

  const loadVideo = useCallback(async (videoId: string) => {
    try {
      const [metadata, structure] = await Promise.all([
        apiClient.getMediaById(videoId),
        apiClient.getVideoStructure(videoId).catch(() => null),
      ]);

      return {
        id: videoId,
        url: metadata.blob_url,
        title: metadata.original_filename,
        duration: metadata.duration,
        scenes: structure?.structure?.scenes || structure?.scenes || [],
        chapters: structure?.structure?.chapters || structure?.chapters || [],
        transcript: metadata.audio_data?.transcription?.segments || [],
      } as VideoData;
    } catch (error) {
      console.error('Failed to load video:', error);
      return null;
    }
  }, []);

  const loadConversation = useCallback(async () => {
    try {
      setIsLoading(true);
      setConversations(loadConversations());
      setChatMessages(loadConversationMessages(resolvedParams.id));

      const conversation = getConversationById(resolvedParams.id);
      if (conversation?.sessionId) {
        setChatSessionId(conversation.sessionId);
      }

      if (conversation?.videoIds && conversation.videoIds.length > 0) {
        const loadedVideos: VideoData[] = [];
        for (const videoId of conversation.videoIds.slice(0, 10)) {
          const videoData = await loadVideo(videoId);
          if (videoData) {
            loadedVideos.push(videoData);
          }
        }

        setSelectedVideos(loadedVideos);
        setSelectedVideo(loadedVideos[0] || null);

        if (loadedVideos.length > 1 || conversation.mode === 'library') {
          setCurrentMode('library');
        }
      } else if (conversation?.videoId) {
        const videoData = await loadVideo(conversation.videoId);
        if (videoData) {
          setSelectedVideo(videoData);
          setSelectedVideos([videoData]);
        }
      }
    } catch (error) {
      console.error('Failed to load conversation:', error);
    } finally {
      setIsLoading(false);
    }
  }, [loadVideo, resolvedParams.id]);

  // Load conversation and associated video
  useEffect(() => {
    loadConversation();
  }, [resolvedParams.id, loadConversation]);

  const handleTimestampClick = (timestamp: number) => {
    setCurrentTime(timestamp);
  };

  useEffect(() => {
    if (chatMessages.length === 0) {
      return;
    }

    const summary: ConversationSummary = {
      id: resolvedParams.id,
      title: getConversationTitle(chatMessages),
      videoId: selectedVideo?.id,
      videoIds: isMultiVideo ? selectedVideos.map((video) => video.id) : undefined,
      videoName: selectedVideo?.title,
      videoNames: isMultiVideo ? selectedVideos.map((video) => video.title || 'Video') : undefined,
      lastMessage: getConversationPreview(chatMessages),
      updatedAt: new Date(),
      mode: isMultiVideo ? 'library' : currentMode,
      sessionId: chatSessionId,
      messageCount: chatMessages.length,
    };

    const updated = upsertConversation(summary);
    setConversations(updated);
    saveConversationMessages(resolvedParams.id, chatMessages);
  }, [
    chatMessages,
    chatSessionId,
    currentMode,
    isMultiVideo,
    resolvedParams.id,
    selectedVideo?.id,
    selectedVideo?.title,
    selectedVideos,
  ]);

  const handleDeleteConversation = (conversationId: string) => {
    const updated = removeConversation(conversationId);
    setConversations(updated);

    if (conversationId === resolvedParams.id) {
      router.push('/chat/new');
    }
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
            conversations={conversations}
            activeConversationId={resolvedParams.id}
            currentMode={currentMode}
            onModeChange={setCurrentMode}
            onNewChat={() => router.push('/chat/new')}
            onSelectConversation={(id) => router.push(`/chat/${id}`)}
            onDeleteConversation={handleDeleteConversation}
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
              conversationId={resolvedParams.id}
              videoId={selectedVideo?.id}
              videoName={selectedVideo?.title}
              videoIds={isMultiVideo ? selectedVideos.map((video) => video.id) : undefined}
              videoNames={isMultiVideo ? selectedVideos.map((video) => video.title || 'Video') : undefined}
              mode={isMultiVideo ? 'library' : currentMode}
              onTimestampClick={handleTimestampClick}
              userName={user?.full_name || user?.email}
              initialMessages={chatMessages}
              initialSessionId={chatSessionId}
              onMessagesChange={setChatMessages}
              onSessionIdChange={setChatSessionId}
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
