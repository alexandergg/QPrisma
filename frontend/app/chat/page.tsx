'use client';

import { useState, useCallback, Suspense } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar, VideoPanel } from '@/components/layout';
import { ChatContainer } from '@/components/chat';
import { useAuth } from '@/contexts/AuthContext';
import type { ChatMessageData } from '@/components/chat';
import {
  type ConversationSummary,
  getConversationPreview,
  getConversationTitle,
  loadConversations,
  removeConversation,
  saveConversationMessages,
  upsertConversation,
} from '@/lib/conversations';
import RequireAuth from '@/components/RequireAuth';
import { X } from 'lucide-react';
import VideoSelectionBar from './new/VideoSelectionBar';
import { VideoSelectorModal, MultiVideoSelectorModal } from './new/VideoSelectorModals';
import UploadModal from './new/UploadModal';
import MultiVideoPanel from './new/MultiVideoPanel';
import { useChatVideos } from './useChatVideos';

function NewChatContent() {
  const router = useRouter();
  const { user } = useAuth();

  // ── Video selection state (hook) ──────────────────────────────────────
  const v = useChatVideos();

  // ── Conversation state ────────────────────────────────────────────────
  const [showLibraryHelp, setShowLibraryHelp] = useState(true);
  const [conversations, setConversations] = useState<ConversationSummary[]>(() => loadConversations());
  const [activeConversationId, setActiveConversationId] = useState<string | undefined>();
  const [chatMessages, setChatMessages] = useState<ChatMessageData[]>([]);
  const [chatSessionId, setChatSessionId] = useState<string | undefined>();

  const persistConversationState = useCallback(
    (nextMessages: ChatMessageData[], nextSessionId?: string) => {
      if (nextMessages.length === 0) return;

      const conversationId = activeConversationId || crypto.randomUUID();
      if (!activeConversationId) setActiveConversationId(conversationId);

      const summary: ConversationSummary = {
        id: conversationId,
        title: getConversationTitle(nextMessages),
        videoId: v.selectedVideo?.id,
        videoIds: v.isMultiVideo ? v.selectedVideos.map((vid) => vid.id) : undefined,
        videoName: v.selectedVideo?.title,
        videoNames: v.isMultiVideo ? v.selectedVideos.map((vid) => vid.title || 'Video') : undefined,
        lastMessage: getConversationPreview(nextMessages),
        updatedAt: new Date(),
        mode: v.isMultiVideo ? 'library' : v.currentMode,
        sessionId: nextSessionId,
        messageCount: nextMessages.length,
      };

      const updated = upsertConversation(summary);
      setConversations(updated);
      saveConversationMessages(conversationId, nextMessages);
    },
    [activeConversationId, v.currentMode, v.isMultiVideo, v.selectedVideo?.id, v.selectedVideo?.title, v.selectedVideos],
  );

  const handleMessagesChange = useCallback(
    (nextMessages: ChatMessageData[]) => {
      setChatMessages(nextMessages);
      persistConversationState(nextMessages, chatSessionId);
    },
    [persistConversationState, chatSessionId],
  );

  const handleSessionIdChange = useCallback(
    (nextSessionId: string | undefined) => {
      setChatSessionId(nextSessionId);
      persistConversationState(chatMessages, nextSessionId);
    },
    [persistConversationState, chatMessages],
  );

  const handleDeleteConversation = (conversationId: string) => {
    const updated = removeConversation(conversationId);
    setConversations(updated);
    if (conversationId === activeConversationId) {
      setActiveConversationId(undefined);
      setChatMessages([]);
      setChatSessionId(undefined);
      router.push('/chat/new');
    }
  };

  return (
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
          activeConversationId={activeConversationId}
          currentMode={v.currentMode}
          onModeChange={v.setCurrentMode}
          onNewChat={() => {
            v.clearSelection();
            setActiveConversationId(undefined);
            setChatMessages([]);
            setChatSessionId(undefined);
            router.push('/chat/new');
          }}
          onSelectConversation={(id) => router.push(`/chat/${id}`)}
          onDeleteConversation={handleDeleteConversation}
        />
      </div>

      {/* Main Content */}
      <div className="relative z-10 flex-1 flex flex-col md:flex-row min-w-0">
        {/* Chat Area */}
        <main
          className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${
            (v.selectedVideo && v.currentMode === 'single') || v.isMultiVideo ? 'md:w-[60%]' : 'w-full'
          }`}
        >
          <VideoSelectionBar
            selectedVideo={v.selectedVideo}
            selectedVideos={v.selectedVideos}
            isMultiVideo={v.isMultiVideo}
            currentMode={v.currentMode}
            onRemoveVideo={v.handleRemoveVideo}
            onClearVideo={v.clearSelection}
            onChangeVideo={() => v.setShowVideoSelector(true)}
            onAddMoreVideos={() => v.setShowMultiVideoSelector(true)}
            onEditSelection={() => v.setShowMultiVideoSelector(true)}
          />

          {/* Library Mode Help */}
          {v.isMultiVideo && showLibraryHelp && (
            <div className="flex items-start gap-3 mx-4 mt-2 px-4 py-3 bg-purple-50/80 border border-purple-100 rounded-xl text-sm text-purple-800">
              <span className="text-purple-500 mt-0.5">💡</span>
              <div className="flex-1">
                <p className="font-medium">Library Mode</p>
                <p className="text-purple-600 mt-0.5">
                  Ask questions across all selected videos. Try &quot;Compare the topics in these videos&quot;,
                  &quot;What do these videos have in common?&quot;, or &quot;Search for [topic] across all videos&quot;.
                </p>
              </div>
              <button
                onClick={() => setShowLibraryHelp(false)}
                className="p-1 hover:bg-purple-100 rounded-lg text-purple-400 hover:text-purple-600 flex-shrink-0"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          <ChatContainer
            conversationId={activeConversationId}
            videoId={v.selectedVideo?.id}
            videoName={v.selectedVideo?.title}
            videoIds={v.isMultiVideo ? v.selectedVideos.map((vid) => vid.id) : undefined}
            videoNames={v.isMultiVideo ? v.selectedVideos.map((vid) => vid.title || 'Video') : undefined}
            mode={v.isMultiVideo ? 'library' : v.currentMode}
            onTimestampClick={(timestamp: number) => v.setCurrentTime(timestamp)}
            onUploadVideo={() => v.setShowUploader(true)}
            onBrowseLibrary={() => v.setShowVideoSelector(true)}
            userName={user?.full_name || user?.email}
            initialMessages={chatMessages}
            initialSessionId={chatSessionId}
            onMessagesChange={handleMessagesChange}
            onSessionIdChange={handleSessionIdChange}
          />
        </main>

        {/* Video Panel (Single Video Mode) */}
        {v.selectedVideo && v.currentMode === 'single' && (
          <div className="w-full md:w-[40%] md:min-w-[400px] md:max-w-[600px] flex-shrink-0 h-[40vh] md:h-screen">
            <VideoPanel
              videoId={v.selectedVideo.id}
              videoUrl={v.selectedVideo.url}
              videoTitle={v.selectedVideo.title}
              duration={v.selectedVideo.duration}
              scenes={v.selectedVideo.scenes}
              chapters={v.selectedVideo.chapters}
              transcript={v.selectedVideo.transcript}
              currentTime={v.currentTime}
              onTimeUpdate={v.setCurrentTime}
              onSeek={v.setCurrentTime}
              isVisible={true}
              onClose={() => v.setSelectedVideo(null)}
            />
          </div>
        )}

        {/* Multi-Video Panel (Library Mode) */}
        {v.isMultiVideo && (
          <MultiVideoPanel
            selectedVideos={v.selectedVideos}
            activeVideoTab={v.activeVideoTab}
            comparisonMode={v.comparisonMode}
            currentTime={v.currentTime}
            onActiveVideoTabChange={v.setActiveVideoTab}
            onSelectedVideoChange={v.setSelectedVideo}
            onComparisonModeToggle={() => v.setComparisonMode(v.comparisonMode === 'tabs' ? 'side-by-side' : 'tabs')}
            onTimeUpdate={v.setCurrentTime}
            onRemoveVideo={v.handleRemoveVideo}
          />
        )}
      </div>

      <VideoSelectorModal
        isOpen={v.showVideoSelector}
        selectedVideoId={v.selectedVideo?.id}
        onSelectVideo={v.handleSelectVideoFromLibrary}
        onClose={() => v.setShowVideoSelector(false)}
      />

      <MultiVideoSelectorModal
        isOpen={v.showMultiVideoSelector}
        selectedVideos={v.selectedVideos}
        onSelectionChange={v.handleMultiVideoSelectionChange}
        onConfirm={v.handleConfirmMultiSelect}
        onClose={() => v.setShowMultiVideoSelector(false)}
      />

      <UploadModal
        isOpen={v.showUploader}
        pendingFiles={v.pendingFiles}
        uploadingVideos={v.uploadingVideos}
        uploadPreset={v.uploadPreset}
        uploadMaxFrames={v.uploadMaxFrames}
        onClose={() => { v.setShowUploader(false); v.setUploadingVideos([]); v.setPendingFiles([]); }}
        onFilesSelected={v.setPendingFiles}
        onRemovePendingFile={(idx) => v.setPendingFiles((prev) => prev.filter((_, i) => i !== idx))}
        onPresetChange={v.setUploadPreset}
        onMaxFramesChange={v.setUploadMaxFrames}
        onUploadingVideosChange={v.setUploadingVideos}
        onUploadComplete={v.handleUploadComplete}
      />
    </div>
  );
}

export default function NewChatPage() {
  return (
    <RequireAuth>
      <Suspense fallback={
        <div className="flex items-center justify-center h-screen">
          <div className="text-gray-500">Loading...</div>
        </div>
      }>
        <NewChatContent />
      </Suspense>
    </RequireAuth>
  );
}
