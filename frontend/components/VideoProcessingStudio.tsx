'use client';

import React, { useState, useEffect } from 'react';
import { Clock, Sparkles, Plus, Grid } from 'lucide-react';
import { apiClient } from '@/lib/api';
import { API_URL } from '@/lib/config';
import { useRouter } from 'next/navigation';
import { StudioSidebar } from './StudioSidebar';
import { StudioUploadView } from './StudioUploadView';
import { StudioLibraryView } from './StudioLibraryView';
import type { MediaItem } from './StudioLibraryView';

interface Preset {
  name: string;
  description: string;
}

export default function VideoProcessingStudio() {
  const router = useRouter();
  const [showUpload, setShowUpload] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<string>('balanced');
  const [maxFrames, setMaxFrames] = useState<number>(100);
  const [mediaList, setMediaList] = useState<MediaItem[]>([]);
  const [loadingMedia, setLoadingMedia] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [useOptimizedPipeline, setUseOptimizedPipeline] = useState(true);
  const [sceneDetectionEnabled, setSceneDetectionEnabled] = useState(true);
  const [hierarchicalSummaryEnabled, setHierarchicalSummaryEnabled] = useState(true);

  useEffect(() => {
    loadPresets();
    loadMediaList();
  }, []);

  const loadPresets = async () => {
    try {
      const response = await fetch(`${API_URL}/presets`);
      const data = await response.json();
      setPresets(data.presets || []);
    } catch (error) {
      console.error('Error loading presets:', error);
      setPresets([]);
    }
  };

  const loadMediaList = async () => {
    try {
      setLoadingMedia(true);
      const response = await apiClient.getMedia();
      setMediaList(response.media || []);
    } catch (error) {
      console.error('Error loading media list:', error);
      setMediaList([]);
    } finally {
      setLoadingMedia(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, mediaId: string) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this video? This action cannot be undone.')) {
      return;
    }
    try {
      await apiClient.deleteMedia(mediaId);
      setMediaList(mediaList.filter(item => item.id !== mediaId));
    } catch (error) {
      console.error('Error deleting media:', error);
      alert('Failed to delete video');
    }
  };

  const filteredMedia = mediaList.filter(item =>
    item.original_filename.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const processedCount = mediaList.filter(m => m.processed).length;
  const pendingCount = mediaList.filter(m => !m.processed).length;

  /* ---------------------------------------------------------------- */
  /*  Upload view                                                      */
  /* ---------------------------------------------------------------- */
  if (showUpload) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 font-sans">
        <div className="fixed inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl" />
          <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl" />
        </div>

        <div className="relative flex min-h-screen">
          <StudioSidebar
            mediaList={mediaList}
            showBackButton
            onBackToLibrary={() => setShowUpload(false)}
          />

          <StudioUploadView
            presets={presets}
            selectedPreset={selectedPreset}
            maxFrames={maxFrames}
            useOptimizedPipeline={useOptimizedPipeline}
            sceneDetectionEnabled={sceneDetectionEnabled}
            hierarchicalSummaryEnabled={hierarchicalSummaryEnabled}
            onPresetChange={setSelectedPreset}
            onMaxFramesChange={setMaxFrames}
            onOptimizedPipelineChange={setUseOptimizedPipeline}
            onSceneDetectionChange={setSceneDetectionEnabled}
            onHierarchicalSummaryChange={setHierarchicalSummaryEnabled}
            onVideoProcessed={(mediaId) => router.push(`/chat/new?videoId=${mediaId}`)}
          />
        </div>
      </div>
    );
  }

  /* ---------------------------------------------------------------- */
  /*  Library view                                                     */
  /* ---------------------------------------------------------------- */
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 font-sans selection:bg-indigo-100 selection:text-indigo-900">
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-gradient-to-br from-indigo-200/30 to-purple-200/30 rounded-full blur-3xl" />
        <div className="absolute bottom-0 -left-40 w-96 h-96 bg-gradient-to-br from-blue-200/20 to-cyan-200/20 rounded-full blur-3xl" />
      </div>

      <div className="relative flex min-h-screen">
        <StudioSidebar mediaList={mediaList}>
          {/* New Upload Button */}
          <button
            onClick={() => setShowUpload(true)}
            className="w-full px-5 py-3.5 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl transition-all font-semibold flex items-center justify-center gap-2 shadow-lg shadow-indigo-500/30 hover:shadow-xl hover:shadow-indigo-500/40 hover:-translate-y-0.5 mb-8"
          >
            <Plus className="w-5 h-5" />
            New Upload
          </button>

          {/* Navigation */}
          <div className="flex-1 overflow-y-auto -mx-2 px-2 space-y-1">
            <div className="px-3 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Library</div>
            <button className="w-full text-left px-4 py-3 bg-indigo-50 rounded-xl text-indigo-700 font-semibold flex items-center gap-3 border border-indigo-100">
              <Grid className="w-4 h-4" />
              All Videos
              <span className="ml-auto bg-indigo-500 text-white text-xs px-2 py-0.5 rounded-full font-bold">{mediaList.length}</span>
            </button>
            <button className="w-full text-left px-4 py-3 hover:bg-gray-100 rounded-xl text-gray-600 hover:text-gray-900 transition-all font-medium flex items-center gap-3">
              <Sparkles className="w-4 h-4" />
              Processed
              <span className="ml-auto text-gray-400 text-xs font-semibold">{processedCount}</span>
            </button>
            <button className="w-full text-left px-4 py-3 hover:bg-gray-100 rounded-xl text-gray-600 hover:text-gray-900 transition-all font-medium flex items-center gap-3">
              <Clock className="w-4 h-4" />
              Pending
              <span className="ml-auto text-gray-400 text-xs font-semibold">{pendingCount}</span>
            </button>
          </div>
        </StudioSidebar>

        <StudioLibraryView
          mediaList={mediaList}
          filteredMedia={filteredMedia}
          loadingMedia={loadingMedia}
          searchQuery={searchQuery}
          viewMode={viewMode}
          processedCount={processedCount}
          pendingCount={pendingCount}
          onSearchQueryChange={setSearchQuery}
          onViewModeChange={setViewMode}
          onDelete={handleDelete}
          onShowUpload={() => setShowUpload(true)}
        />
      </div>
    </div>
  );
}
