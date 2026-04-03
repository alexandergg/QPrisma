'use client';

import { useState, useCallback, Suspense } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar, VideoPanel } from '@/components/layout';
import { ChatContainer } from '@/components/chat';
import { useAuth } from '@/contexts/AuthContext';
import type { ChatMessageData } from '@/components/chat';
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

  // ── UI state ──────────────────────────────────────────────────────────
  const [showLibraryHelp, setShowLibraryHelp] = useState(true);

  const handleMessagesChange = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    (_nextMessages: ChatMessageData[]) => {
      // No-op: conversation persistence removed; placeholder for future server-side sync
    },
    [],
  );

  const handleSessionIdChange = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    (_nextSessionId: string | undefined) => {
      // No-op: conversation persistence removed; placeholder for future server-side sync
    },
    [],
  );

  return (
    <div className="flex h-screen bg-[var(--background)] overflow-hidden">
      {/* Decorative Elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl dark:from-indigo-900/20 dark:to-purple-900/20"></div>
        <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl dark:from-blue-900/15 dark:to-cyan-900/15"></div>
      </div>

      {/* Sidebar */}
      <div className="relative z-10 flex-shrink-0">
        <Sidebar
          currentMode={v.currentMode}
          onModeChange={v.setCurrentMode}
          onNewChat={() => {
            v.clearSelection();
            router.push('/chat/new');
          }}
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
            <div className="flex items-start gap-3 mx-4 mt-2 px-4 py-3 bg-purple-50/80 dark:bg-purple-500/10 border border-purple-100 dark:border-purple-500/20 rounded-xl text-sm text-purple-800 dark:text-purple-300">
              <span className="text-purple-500 mt-0.5">💡</span>
              <div className="flex-1">
                <p className="font-medium">Library Mode</p>
                <p className="text-purple-600 dark:text-purple-400 mt-0.5">
                  Ask questions across all selected videos. Try &quot;Compare the topics in these videos&quot;,
                  &quot;What do these videos have in common?&quot;, or &quot;Search for [topic] across all videos&quot;.
                </p>
              </div>
              <button
                onClick={() => setShowLibraryHelp(false)}
                className="p-1 hover:bg-purple-100 dark:hover:bg-purple-500/20 rounded-lg text-purple-400 hover:text-purple-600 dark:hover:text-purple-300 flex-shrink-0"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          <ChatContainer
            videoId={v.selectedVideo?.id}
            videoName={v.selectedVideo?.title}
            videoIds={v.isMultiVideo ? v.selectedVideos.map((vid) => vid.id) : undefined}
            videoNames={v.isMultiVideo ? v.selectedVideos.map((vid) => vid.title || 'Video') : undefined}
            mode={v.isMultiVideo ? 'library' : v.currentMode}
            onTimestampClick={(timestamp: number) => v.setCurrentTime(timestamp)}
            onUploadVideo={() => v.setShowUploader(true)}
            onBrowseLibrary={() => v.setShowVideoSelector(true)}
            onSelectVideoById={v.handleSelectVideoById}
            userName={user?.full_name || user?.email}
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
          <div className="text-[var(--text-secondary)]">Loading...</div>
        </div>
      }>
        <NewChatContent />
      </Suspense>
    </RequireAuth>
  );
}
