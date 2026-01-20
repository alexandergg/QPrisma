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
import { X, Film, Library, Settings2, ChevronDown } from 'lucide-react';

interface Scene {
  scene_id: number;
  start_time: number;
  end_time: number;
  summary?: string;
}

interface Chapter {
  chapter_id: number;
  title: string;
  start_time: number;
  end_time: number;
}

interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  text: string;
}

interface VideoData {
  id: string;
  url?: string;
  title?: string;
  duration?: number;
  scenes?: Scene[];
  chapters?: Chapter[];
  transcript?: TranscriptSegment[];
}

interface LibraryVideo {
  id: string;
  original_filename: string;
  blob_url?: string;
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
  const [uploadPreset, setUploadPreset] = useState<string>('balanced');
  const [uploadMaxFrames, setUploadMaxFrames] = useState(200);
  const [pendingFile, setPendingFile] = useState<File | null>(null);

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

  const handleSelectVideoFromLibrary = async (video: LibraryVideo) => {
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
                  setPendingFile(null);
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
                  setPendingFile(null);
                  await handleUploadComplete(mediaId);
                }}
                onError={(error) => {
                  console.error('Processing failed:', error);
                  setUploadingVideo({ ...uploadingVideo, status: 'error' });
                }}
                onViewVideo={async (mediaId) => {
                  setUploadingVideo(null);
                  setShowUploader(false);
                  setPendingFile(null);
                  await handleUploadComplete(mediaId);
                }}
              />
            ) : pendingFile ? (
              /* Configuration step - file selected, configure before upload */
              <div className="space-y-6">
                {/* Selected file info */}
                <div className="bg-indigo-50 rounded-xl p-4 flex items-center gap-4">
                  <div className="w-12 h-12 bg-indigo-100 rounded-xl flex items-center justify-center">
                    <Film className="w-6 h-6 text-indigo-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-gray-900 truncate">{pendingFile.name}</p>
                    <p className="text-sm text-gray-500">
                      {(pendingFile.size / (1024 * 1024)).toFixed(1)} MB
                    </p>
                  </div>
                  <button
                    onClick={() => setPendingFile(null)}
                    className="p-2 hover:bg-indigo-100 rounded-lg text-indigo-600"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {/* Processing Options */}
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-gray-700">
                    <Settings2 className="w-4 h-4 text-indigo-500" />
                    Processing Options
                  </div>

                  {/* Preset Selection */}
                  <div>
                    <label className="block text-sm font-medium text-gray-600 mb-2">
                      Quality Preset
                    </label>
                    <div className="relative">
                      <select
                        value={uploadPreset}
                        onChange={(e) => setUploadPreset(e.target.value)}
                        className="w-full px-4 py-3 bg-gray-50 text-gray-900 rounded-xl border border-gray-200 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 focus:outline-none appearance-none cursor-pointer"
                      >
                        <option value="fast_preview">⚡ Fast Preview - Quick scan (50 frames)</option>
                        <option value="balanced">⚖️ Balanced - Good coverage (200 frames)</option>
                        <option value="high_quality">🎯 High Quality - Deep analysis (600 frames)</option>
                        <option value="adaptive">✨ Adaptive - Auto-adjust by duration</option>
                        <option value="deep_analysis">🔬 Deep Analysis - Long videos (1000 frames)</option>
                        <option value="ultra_deep">🔭 Ultra Deep - Very long 4+ hrs (2000 frames)</option>
                        <option value="interview_mode">🎙️ Interview - Audio priority (200 frames)</option>
                        <option value="action_mode">🎬 Action - Motion detection (800 frames)</option>
                      </select>
                      <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                    </div>
                  </div>

                  {/* Frame Count */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-sm font-medium text-gray-600">
                        Analysis Depth
                      </label>
                      <span className="text-sm font-semibold text-indigo-600">
                        {uploadMaxFrames} frames
                      </span>
                    </div>
                    <input
                      type="range"
                      min="50"
                      max="2000"
                      step="50"
                      value={uploadMaxFrames}
                      onChange={(e) => setUploadMaxFrames(parseInt(e.target.value))}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                    />
                    <div className="flex justify-between text-xs text-gray-400 mt-1">
                      <span>Quick</span>
                      <span>Deep</span>
                    </div>
                  </div>
                </div>

                {/* Start Processing Button */}
                <button
                  onClick={async () => {
                    const file = pendingFile;
                    setUploadingVideo({
                      fileName: file.name,
                      fileSize: file.size,
                      status: 'uploading',
                    });
                    
                    try {
                      const response = await apiClient.uploadVideoOptimized(file, {
                        preset: uploadPreset,
                        maxFrames: uploadMaxFrames,
                        useSceneDetection: true,
                        useHierarchicalSummary: true,
                      });
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
                  }}
                  className="w-full py-3 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl font-semibold transition-all shadow-lg shadow-indigo-500/30"
                >
                  Start Processing
                </button>
              </div>
            ) : (
              <UploadZone
                onFilesSelected={(files) => {
                  if (files.length > 0) {
                    setPendingFile(files[0]);
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
