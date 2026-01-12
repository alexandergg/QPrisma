'use client';

import React, { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Sidebar, VideoPanel } from '@/components/layout';
import { ChatContainer } from '@/components/chat';
import { VideoGrid } from '@/components/library';
import { UploadZone, ProcessingCard } from '@/components/upload';
import { useAuth } from '@/contexts/AuthContext';
import { apiClient } from '@/lib/api';
import RequireAuth from '@/components/RequireAuth';
import { X, Film, Library } from 'lucide-react';

interface VideoData {
  id: string;
  url?: string;
  title?: string;
  duration?: number;
  scenes?: any[];
  chapters?: any[];
  transcript?: any[];
}

interface UploadingVideo {
  fileName: string;
  fileSize: number;
  mediaId?: string;
  jobId?: string;
  status: 'uploading' | 'processing' | 'completed' | 'error';
}

function NewChatContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();

  const [currentMode, setCurrentMode] = useState<'single' | 'library'>('single');
  const [selectedVideo, setSelectedVideo] = useState<VideoData | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [showVideoSelector, setShowVideoSelector] = useState(false);
  const [showUploader, setShowUploader] = useState(false);
  const [isLoadingVideo, setIsLoadingVideo] = useState(false);
  const [uploadingVideo, setUploadingVideo] = useState<UploadingVideo | null>(null);

  // Check for videoId in URL params
  useEffect(() => {
    const videoId = searchParams.get('videoId');
    if (videoId) {
      loadVideo(videoId);
    }
  }, [searchParams]);

  const loadVideo = async (videoId: string) => {
    try {
      setIsLoadingVideo(true);
      const [metadata, structure] = await Promise.all([
        apiClient.getVideoMetadata(videoId),
        apiClient.getVideoStructure(videoId).catch(() => null),
      ]);

      setSelectedVideo({
        id: videoId,
        url: metadata.blob_url,
        title: metadata.original_filename,
        duration: metadata.duration,
        scenes: structure?.structure?.scenes || structure?.scenes || [],
        chapters: structure?.structure?.chapters || structure?.chapters || [],
        transcript: metadata.audio_data?.transcription?.segments || [],
      });
    } catch (error) {
      console.error('Failed to load video:', error);
    } finally {
      setIsLoadingVideo(false);
    }
  };

  const handleSelectVideoFromLibrary = async (video: any) => {
    setShowVideoSelector(false);
    await loadVideo(video.id);
  };

  const handleTimestampClick = (timestamp: number) => {
    setCurrentTime(timestamp);
  };

  const handleUploadComplete = async (mediaId: string) => {
    setShowUploader(false);
    await loadVideo(mediaId);
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
          conversations={[]}
          currentMode={currentMode}
          onModeChange={setCurrentMode}
          onNewChat={() => {
            setSelectedVideo(null);
            router.push('/chat/new');
          }}
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
          {/* Video Selection Bar (when video is selected) */}
          {selectedVideo && currentMode === 'single' && (
            <div className="flex items-center gap-3 px-4 py-3 bg-white/80 backdrop-blur-sm border-b border-gray-100">
              <div className="flex items-center gap-2 px-3 py-1.5 bg-indigo-50 text-indigo-700 rounded-full">
                <Film className="w-4 h-4" />
                <span className="text-sm font-medium truncate max-w-[200px]">
                  {selectedVideo.title}
                </span>
                <button
                  onClick={() => setSelectedVideo(null)}
                  className="p-0.5 hover:bg-indigo-100 rounded-full"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
              <button
                onClick={() => setShowVideoSelector(true)}
                className="text-sm text-gray-500 hover:text-indigo-600"
              >
                Change video
              </button>
            </div>
          )}

          {/* Chat Container */}
          <ChatContainer
            videoId={selectedVideo?.id}
            videoName={selectedVideo?.title}
            videoUrl={selectedVideo?.url}
            mode={currentMode}
            onTimestampClick={handleTimestampClick}
            onUploadVideo={() => setShowUploader(true)}
            onBrowseLibrary={() => setShowVideoSelector(true)}
            userName={user?.full_name || user?.email}
          />
        </main>

        {/* Video Panel (Single Video Mode) */}
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
              onClose={() => setSelectedVideo(null)}
            />
          </div>
        )}
      </div>

      {/* Video Selector Modal */}
      {showVideoSelector && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[80vh] overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <h2 className="text-xl font-semibold text-gray-900">Select a Video</h2>
              <button
                onClick={() => setShowVideoSelector(false)}
                className="p-2 hover:bg-gray-100 rounded-lg text-gray-500"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="h-[60vh]">
              <VideoGrid
                onSelectVideo={handleSelectVideoFromLibrary}
                selectedVideoId={selectedVideo?.id}
              />
            </div>
          </div>
        </div>
      )}

      {/* Upload Modal */}
      {showUploader && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-gray-900">Upload Video</h2>
              <button
                onClick={() => {
                  setShowUploader(false);
                  setUploadingVideo(null);
                }}
                className="p-2 hover:bg-gray-100 rounded-lg text-gray-500"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            {/* Show ProcessingCard when uploading/processing */}
            {uploadingVideo ? (
              <ProcessingCard
                fileName={uploadingVideo.fileName}
                fileSize={uploadingVideo.fileSize}
                jobId={uploadingVideo.jobId}
                mediaId={uploadingVideo.mediaId}
                onComplete={async (mediaId) => {
                  setUploadingVideo(null);
                  setShowUploader(false);
                  await handleUploadComplete(mediaId);
                }}
                onError={(error) => {
                  console.error('Processing failed:', error);
                  setUploadingVideo({ ...uploadingVideo, status: 'error' });
                }}
                onViewVideo={async (mediaId) => {
                  setUploadingVideo(null);
                  setShowUploader(false);
                  await handleUploadComplete(mediaId);
                }}
              />
            ) : (
              <UploadZone
                onFilesSelected={async (files) => {
                  if (files.length > 0) {
                    const file = files[0];
                    // Show uploading state
                    setUploadingVideo({
                      fileName: file.name,
                      fileSize: file.size,
                      status: 'uploading',
                    });
                    
                    try {
                      const response = await apiClient.uploadVideoOptimized(file, {
                        useSceneDetection: true,
                        useHierarchicalSummary: true,
                      });
                      // Update with job info - processing will be tracked via WebSocket
                      setUploadingVideo({
                        fileName: file.name,
                        fileSize: file.size,
                        mediaId: response.media_id,
                        jobId: response.job_id,
                        status: 'processing',
                      });
                    } catch (error) {
                      console.error('Upload failed:', error);
                      setUploadingVideo({
                        fileName: file.name,
                        fileSize: file.size,
                        status: 'error',
                      });
                    }
                  }
                }}
              />
            )}
          </div>
        </div>
      )}
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
