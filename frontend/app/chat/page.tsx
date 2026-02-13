'use client';

import React, { useState, useEffect, useCallback, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Sidebar, VideoPanel } from '@/components/layout';
import { ChatContainer } from '@/components/chat';
import { VideoGrid } from '@/components/library';
import { UploadZone, ProcessingCard } from '@/components/upload';
import { useAuth } from '@/contexts/AuthContext';
import { apiClient } from '@/lib/api';
import RequireAuth from '@/components/RequireAuth';
import { X, Film, Settings2, ChevronDown, Library, Columns2 } from 'lucide-react';
import { ChunkedUploader, shouldUseChunkedUpload, UploadProgress } from '@/lib/chunked-upload';

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
  id: string;
  fileName: string;
  fileSize: number;
  mediaId?: string;
  jobId?: string;
  status: 'uploading' | 'processing' | 'completed' | 'error';
  progress?: number;
  uploadSpeed?: string;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function NewChatContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();

  const [currentMode, setCurrentMode] = useState<'single' | 'library'>('single');
  const [selectedVideo, setSelectedVideo] = useState<VideoData | null>(null);
  const [selectedVideos, setSelectedVideos] = useState<VideoData[]>([]);
  const [currentTime, setCurrentTime] = useState(0);
  const [showVideoSelector, setShowVideoSelector] = useState(false);
  const [showMultiVideoSelector, setShowMultiVideoSelector] = useState(false);
  const [showUploader, setShowUploader] = useState(false);
  const [uploadingVideos, setUploadingVideos] = useState<UploadingVideo[]>([]);
  const [uploadPreset, setUploadPreset] = useState<string>('balanced');
  const [uploadMaxFrames, setUploadMaxFrames] = useState(200);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [activeVideoTab, setActiveVideoTab] = useState(0);
  const [comparisonMode, setComparisonMode] = useState<'tabs' | 'side-by-side'>('tabs');
  const [showLibraryHelp, setShowLibraryHelp] = useState(true);

  const isMultiVideo = selectedVideos.length > 1;

  const loadVideo = useCallback(async (videoId: string) => {
    try {
      const [metadata, structure] = await Promise.all([
        apiClient.getVideoMetadata(videoId),
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

  // Check for videoId in URL params
  useEffect(() => {
    const videoId = searchParams.get('videoId');
    if (videoId) {
      Promise.resolve().then(async () => {
        const videoData = await loadVideo(videoId);
        if (videoData) {
          setSelectedVideo(videoData);
        }
      });
    }
  }, [searchParams, loadVideo]);

  const handleSelectVideoFromLibrary = async (video: LibraryVideo) => {
    setShowVideoSelector(false);
    const videoData = await loadVideo(video.id);
    if (videoData) {
      setSelectedVideo(videoData);
      setSelectedVideos([videoData]);
    }
  };

  const handleMultiVideoSelectionChange = async (ids: string[]) => {
    // Load all selected videos
    const videos: VideoData[] = [];
    for (const id of ids.slice(0, 10)) {
      // Check if already loaded
      const existing = selectedVideos.find((v) => v.id === id);
      if (existing) {
        videos.push(existing);
      } else {
        const videoData = await loadVideo(id);
        if (videoData) videos.push(videoData);
      }
    }
    setSelectedVideos(videos);
    if (videos.length === 1) {
      setSelectedVideo(videos[0]);
    } else if (videos.length > 1) {
      setSelectedVideo(videos[0]); // Primary video for the viewer
    } else {
      setSelectedVideo(null);
    }
  };

  const handleConfirmMultiSelect = () => {
    setShowMultiVideoSelector(false);
    if (selectedVideos.length > 1) {
      setCurrentMode('library');
    }
  };

  const handleRemoveVideo = (videoId: string) => {
    const updated = selectedVideos.filter((v) => v.id !== videoId);
    setSelectedVideos(updated);
    if (updated.length !== 2) setComparisonMode('tabs');
    if (activeVideoTab >= updated.length) {
      setActiveVideoTab(Math.max(0, updated.length - 1));
    }
    if (updated.length === 0) {
      setSelectedVideo(null);
      setCurrentMode('single');
    } else if (updated.length === 1) {
      setSelectedVideo(updated[0]);
      setCurrentMode('single');
    } else {
      setSelectedVideo(updated[0]);
    }
  };

  const handleTimestampClick = (timestamp: number) => {
    setCurrentTime(timestamp);
  };

  const handleUploadComplete = async (mediaId: string) => {
    setShowUploader(false);
    const videoData = await loadVideo(mediaId);
    if (videoData) {
      setSelectedVideo(videoData);
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
      <div className="relative z-10 flex-1 flex flex-col md:flex-row min-w-0">
        {/* Chat Area */}
        <main
          className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${
            (selectedVideo && currentMode === 'single') || isMultiVideo ? 'md:w-[60%]' : 'w-full'
          }`}
        >
          {/* Video Selection Bar */}
          {(selectedVideo || isMultiVideo) && (
            <div className="flex items-center gap-3 px-4 py-3 bg-white/80 backdrop-blur-sm border-b border-gray-100">
              {isMultiVideo ? (
                <>
                  <div className="flex items-center gap-2 px-3 py-1.5 bg-purple-50 text-purple-700 rounded-full">
                    <Library className="w-4 h-4" />
                    <span className="text-sm font-medium">
                      {selectedVideos.length} videos selected
                    </span>
                  </div>
                  <div className="flex items-center gap-1 overflow-x-auto max-w-[40%] md:max-w-[60%]">
                    {selectedVideos.map((v) => (
                      <div
                        key={v.id}
                        className="flex items-center gap-1 px-2 py-1 bg-indigo-50 text-indigo-700 rounded-full text-xs whitespace-nowrap"
                      >
                        <Film className="w-3 h-3" />
                        <span className="max-w-[120px] truncate">{v.title}</span>
                        <button
                          onClick={() => handleRemoveVideo(v.id)}
                          className="p-0.5 hover:bg-indigo-100 rounded-full"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={() => setShowMultiVideoSelector(true)}
                    className="text-sm text-gray-500 hover:text-purple-600"
                  >
                    Edit selection
                  </button>
                </>
              ) : selectedVideo && currentMode === 'single' ? (
                <>
                  <div className="flex items-center gap-2 px-3 py-1.5 bg-indigo-50 text-indigo-700 rounded-full">
                    <Film className="w-4 h-4" />
                    <span className="text-sm font-medium truncate max-w-[200px]">
                      {selectedVideo.title}
                    </span>
                    <button
                      onClick={() => {
                        setSelectedVideo(null);
                        setSelectedVideos([]);
                      }}
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
                  <button
                    onClick={() => setShowMultiVideoSelector(true)}
                    className="text-sm text-gray-500 hover:text-purple-600 ml-1"
                  >
                    + Add more videos
                  </button>
                </>
              ) : null}
            </div>
          )}

          {/* Library Mode Help */}
          {isMultiVideo && showLibraryHelp && (
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

          {/* Chat Container */}
            <ChatContainer
              videoId={selectedVideo?.id}
              videoName={selectedVideo?.title}
              videoIds={isMultiVideo ? selectedVideos.map((v) => v.id) : undefined}
              videoNames={isMultiVideo ? selectedVideos.map((v) => v.title || 'Video') : undefined}
              mode={isMultiVideo ? 'library' : currentMode}
              onTimestampClick={handleTimestampClick}
              onUploadVideo={() => setShowUploader(true)}
              onBrowseLibrary={() => setShowVideoSelector(true)}
              userName={user?.full_name || user?.email}
            />
        </main>

        {/* Video Panel (Single Video Mode) */}
        {selectedVideo && currentMode === 'single' && (
          <div className="w-full md:w-[40%] md:min-w-[400px] md:max-w-[600px] flex-shrink-0 h-[40vh] md:h-screen">
            <VideoPanel
              videoId={selectedVideo.id}
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

        {/* Multi-Video Panel (Library Mode) */}
        {isMultiVideo && (
          <div className="w-full md:w-[40%] md:min-w-[400px] md:max-w-[600px] flex-shrink-0 h-[40vh] md:h-screen flex flex-col">
            {/* Video Tabs */}
            <div className="flex border-b border-gray-200 bg-white overflow-x-auto">
              {selectedVideos.map((v, idx) => (
                <button
                  key={v.id}
                  onClick={() => {
                    setActiveVideoTab(idx);
                    setSelectedVideo(v);
                  }}
                  className={`flex items-center gap-1.5 px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-colors ${
                    activeVideoTab === idx
                      ? 'border-purple-500 text-purple-700 bg-purple-50/50'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  <Film className="w-3.5 h-3.5" />
                  <span className="max-w-[100px] truncate">{v.title}</span>
                </button>
              ))}
              {selectedVideos.length === 2 && (
                <button
                  onClick={() => setComparisonMode(comparisonMode === 'tabs' ? 'side-by-side' : 'tabs')}
                  className={`ml-auto flex items-center gap-1.5 px-3 py-2 text-xs whitespace-nowrap border-b-2 transition-colors ${
                    comparisonMode === 'side-by-side'
                      ? 'border-purple-500 text-purple-700 bg-purple-50/50'
                      : 'border-transparent text-gray-400 hover:text-gray-600'
                  }`}
                  title="Toggle side-by-side view"
                >
                  <Columns2 className="w-3.5 h-3.5" />
                  <span>Compare</span>
                </button>
              )}
            </div>
            {/* Video Content */}
            {comparisonMode === 'side-by-side' && selectedVideos.length === 2 ? (
              <div className="flex-1 min-h-0 flex flex-col">
                {selectedVideos.map((v, idx) => (
                  <div key={v.id} className="flex-1 min-h-0 border-b border-gray-200 last:border-b-0">
                    <VideoPanel
                      videoId={v.id}
                      videoUrl={v.url}
                      videoTitle={v.title}
                      duration={v.duration}
                      scenes={v.scenes}
                      chapters={v.chapters}
                      transcript={v.transcript}
                      currentTime={currentTime}
                      onTimeUpdate={setCurrentTime}
                      onSeek={setCurrentTime}
                      isVisible={true}
                      onClose={() => handleRemoveVideo(v.id)}
                    />
                  </div>
                ))}
              </div>
            ) : selectedVideos[activeVideoTab] ? (
              <div className="flex-1 min-h-0">
                <VideoPanel
                  videoId={selectedVideos[activeVideoTab].id}
                  videoUrl={selectedVideos[activeVideoTab].url}
                  videoTitle={selectedVideos[activeVideoTab].title}
                  duration={selectedVideos[activeVideoTab].duration}
                  scenes={selectedVideos[activeVideoTab].scenes}
                  chapters={selectedVideos[activeVideoTab].chapters}
                  transcript={selectedVideos[activeVideoTab].transcript}
                  currentTime={currentTime}
                  onTimeUpdate={setCurrentTime}
                  onSeek={setCurrentTime}
                  isVisible={true}
                  onClose={() => handleRemoveVideo(selectedVideos[activeVideoTab].id)}
                />
              </div>
            ) : null}
          </div>
        )}
      </div>

      {/* Video Selector Modal (single) */}
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

      {/* Multi-Video Selector Modal */}
      {showMultiVideoSelector && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[80vh] overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div>
                <h2 className="text-xl font-semibold text-gray-900">Select Multiple Videos</h2>
                <p className="text-sm text-gray-500 mt-1">
                  Select up to 10 videos to chat across them. {selectedVideos.length > 0 && `(${selectedVideos.length} selected)`}
                </p>
              </div>
              <button
                onClick={() => setShowMultiVideoSelector(false)}
                className="p-2 hover:bg-gray-100 rounded-lg text-gray-500"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="h-[50vh]">
              <VideoGrid
                selectionMode="multiple"
                selectedVideoIds={selectedVideos.map((v) => v.id)}
                onSelectionChange={handleMultiVideoSelectionChange}
              />
            </div>
            <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-gray-50">
              <span className="text-sm text-gray-600">
                {selectedVideos.length === 0
                  ? 'No videos selected'
                  : `${selectedVideos.length} video${selectedVideos.length !== 1 ? 's' : ''} selected`}
              </span>
              <button
                onClick={handleConfirmMultiSelect}
                disabled={selectedVideos.length === 0}
                className="px-6 py-2 bg-gradient-to-r from-purple-500 to-indigo-600 hover:from-purple-600 hover:to-indigo-700 disabled:opacity-50 text-white rounded-xl font-semibold transition-all shadow-lg shadow-purple-500/30"
              >
                {selectedVideos.length > 1 ? `Chat with ${selectedVideos.length} Videos` : 'Confirm Selection'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Upload Modal */}
      {showUploader && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-gray-900">
                {pendingFiles.length > 1
                  ? `Upload ${pendingFiles.length} Videos`
                  : 'Upload Video'}
              </h2>
              <button
                onClick={() => {
                  setShowUploader(false);
                  setUploadingVideos([]);
                  setPendingFiles([]);
                }}
                className="p-2 hover:bg-gray-100 rounded-lg text-gray-500"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Show ProcessingCards when uploading/processing */}
            {uploadingVideos.length > 0 ? (
              <div className="space-y-4">
                {uploadingVideos.map((video) => (
                  <ProcessingCard
                    key={video.id}
                    fileName={video.fileName}
                    fileSize={video.fileSize}
                    jobId={video.jobId}
                    mediaId={video.mediaId}
                    uploadProgress={video.progress}
                    uploadSpeed={video.uploadSpeed}
                    onComplete={async (mediaId) => {
                      setUploadingVideos((prev) =>
                        prev.map((v) =>
                          v.id === video.id || v.mediaId === mediaId
                            ? { ...v, status: 'completed' }
                            : v
                        )
                      );
                      await handleUploadComplete(mediaId);
                    }}
                    onError={(error) => {
                      console.error('Processing failed:', error);
                      setUploadingVideos((prev) =>
                        prev.map((v) =>
                          v.id === video.id ? { ...v, status: 'error' } : v
                        )
                      );
                    }}
                    onViewVideo={async (mediaId) => {
                      setShowUploader(false);
                      setUploadingVideos([]);
                      setPendingFiles([]);
                      await handleUploadComplete(mediaId);
                    }}
                  />
                ))}
              </div>
            ) : pendingFiles.length > 0 ? (
              /* Configuration step - files selected, configure before upload */
              <div className="space-y-6">
                {/* Selected files list */}
                <div className="space-y-2">
                  {pendingFiles.map((file, idx) => (
                    <div key={idx} className="bg-indigo-50 rounded-xl p-3 flex items-center gap-3">
                      <div className="w-10 h-10 bg-indigo-100 rounded-lg flex items-center justify-center flex-shrink-0">
                        <Film className="w-5 h-5 text-indigo-600" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-gray-900 truncate text-sm">{file.name}</p>
                        <p className="text-xs text-gray-500">
                          {(file.size / (1024 * 1024)).toFixed(1)} MB
                        </p>
                      </div>
                      <button
                        onClick={() => setPendingFiles((prev) => prev.filter((_, i) => i !== idx))}
                        className="p-1.5 hover:bg-indigo-100 rounded-lg text-indigo-600 flex-shrink-0"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>

                {/* Processing Options */}
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-gray-700">
                    <Settings2 className="w-4 h-4 text-indigo-500" />
                    Processing Options
                    {pendingFiles.length > 1 && (
                      <span className="text-xs text-gray-400 font-normal">(applied to all files)</span>
                    )}
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
                  onClick={() => {
                    // Create entries for all files
                    const entries: UploadingVideo[] = pendingFiles.map((file) => ({
                      id: crypto.randomUUID(),
                      fileName: file.name,
                      fileSize: file.size,
                      status: 'uploading' as const,
                    }));
                    setUploadingVideos(entries);

                    // Upload all files concurrently
                    pendingFiles.forEach((file, idx) => {
                      const entry = entries[idx];
                      (async () => {
                        try {
                          let response: { media_id: string; job_id?: string };

                          if (shouldUseChunkedUpload(file)) {
                            const uploader = new ChunkedUploader(file, {
                              preset: uploadPreset,
                              maxFrames: uploadMaxFrames,
                              useSceneDetection: true,
                              useHierarchicalSummary: true,
                              blockSizeMb: 8,
                              concurrency: 4,
                              onProgress: (progress: UploadProgress) => {
                                setUploadingVideos((prev) =>
                                  prev.map((v) =>
                                    v.id === entry.id
                                      ? {
                                          ...v,
                                          progress: progress.percent,
                                          uploadSpeed: progress.speedBytesPerSecond
                                            ? `${formatBytes(progress.speedBytesPerSecond)}/s`
                                            : undefined,
                                        }
                                      : v
                                  )
                                );
                              },
                            });
                            const result = await uploader.upload();
                            if (!result.success || !result.mediaId) {
                              throw new Error(result.error || 'Chunked upload failed');
                            }
                            response = { media_id: result.mediaId, job_id: result.jobId };
                          } else {
                            response = await apiClient.uploadVideoOptimized(file, {
                              preset: uploadPreset,
                              maxFrames: uploadMaxFrames,
                              useSceneDetection: true,
                              useHierarchicalSummary: true,
                            });
                          }

                          setUploadingVideos((prev) =>
                            prev.map((v) =>
                              v.id === entry.id
                                ? {
                                    ...v,
                                    mediaId: response.media_id,
                                    jobId: response.job_id,
                                    status: 'processing',
                                    progress: undefined,
                                    uploadSpeed: undefined,
                                  }
                                : v
                            )
                          );
                        } catch (error) {
                          console.error('Upload failed:', error);
                          setUploadingVideos((prev) =>
                            prev.map((v) =>
                              v.id === entry.id
                                ? {
                                    ...v,
                                    status: 'error',
                                    progress: undefined,
                                    uploadSpeed: undefined,
                                  }
                                : v
                            )
                          );
                        }
                      })().catch(() => {});
                    });
                  }}
                  className="w-full py-3 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl font-semibold transition-all shadow-lg shadow-indigo-500/30"
                >
                  {pendingFiles.length > 1
                    ? `Start Processing ${pendingFiles.length} Videos`
                    : 'Start Processing'}
                </button>
              </div>
            ) : (
              <UploadZone
                onFilesSelected={(files) => {
                  if (files.length > 0) {
                    setPendingFiles(files);
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
