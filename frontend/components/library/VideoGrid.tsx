'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Search, Grid, List, Film, RefreshCw } from 'lucide-react';
import VideoCard from './VideoCard';
import { VideoListItem } from './VideoListItem';
import type { Video } from './VideoListItem';
import { apiClient } from '@/lib/api';
import { Spinner, Button } from '@/components/ui';

interface VideoGridProps {
  onSelectVideo?: (video: Video) => void;
  onDeleteVideo?: (videoId: string) => void;
  selectedVideoId?: string;
  selectionMode?: 'single' | 'multiple';
  selectedVideoIds?: string[];
  onSelectionChange?: (ids: string[]) => void;
}

type ViewMode = 'grid' | 'list';
type SortOption = 'newest' | 'oldest' | 'name' | 'size';

export default function VideoGrid({
  onSelectVideo,
  onDeleteVideo,
  selectedVideoId,
  selectionMode = 'single',
  selectedVideoIds = [],
  onSelectionChange,
}: VideoGridProps) {
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [sortBy, setSortBy] = useState<SortOption>('newest');

  const loadVideos = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await apiClient.getMedia();
      setVideos(response.media || []);
    } catch (err) {
      console.error('Failed to load videos:', err);
      setError('Failed to load videos');
    } finally {
      setLoading(false);
    }
  }, []);

  // Load videos
  useEffect(() => {
    loadVideos();
  }, [loadVideos]);

  // Filter and sort videos
  const filteredVideos = videos
    .filter((video) =>
      video.original_filename.toLowerCase().includes(searchQuery.toLowerCase())
    )
    .sort((a, b) => {
      switch (sortBy) {
        case 'newest':
          return new Date(b.uploaded_at || 0).getTime() - new Date(a.uploaded_at || 0).getTime();
        case 'oldest':
          return new Date(a.uploaded_at || 0).getTime() - new Date(b.uploaded_at || 0).getTime();
        case 'name':
          return a.original_filename.localeCompare(b.original_filename);
        case 'size':
          return (b.file_size || 0) - (a.file_size || 0);
        default:
          return 0;
      }
    });

  const handleVideoSelect = useCallback((video: Video) => {
    if (selectionMode === 'single') {
      onSelectVideo?.(video);
    } else {
      const isSelected = selectedVideoIds.includes(video.id);
      const newSelection = isSelected
        ? selectedVideoIds.filter((id) => id !== video.id)
        : [...selectedVideoIds, video.id];
      onSelectionChange?.(newSelection);
    }
  }, [selectionMode, onSelectVideo, selectedVideoIds, onSelectionChange]);

  const handleDelete = useCallback(async (videoId: string) => {
    if (!confirm('Are you sure you want to delete this video?')) return;

    try {
      await apiClient.deleteMedia(videoId);
      setVideos((prev) => prev.filter((v) => v.id !== videoId));
      onDeleteVideo?.(videoId);
    } catch (err) {
      console.error('Failed to delete video:', err);
      alert('Failed to delete video');
    }
  }, [onDeleteVideo]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <Spinner size="lg" className="text-[var(--amber-9)] mx-auto mb-3" />
          <p className="text-gray-500">Loading videos...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <p className="text-red-500 mb-3">{error}</p>
          <Button onClick={loadVideos} variant="primary" size="md" className="mx-auto">
            <RefreshCw className="w-4 h-4" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 md:gap-4 p-3 md:p-4 border-b border-[var(--sage-3)] bg-[var(--surface)]/50 backdrop-blur-sm">
        {/* Search */}
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search videos..."
            className="w-full pl-10 pr-4 py-2.5 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-xl)] text-sm focus:outline-none focus:ring-2 focus:ring-amber-4 focus:border-amber-6"
          />
        </div>

        {/* Sort */}
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortOption)}
          className="hidden sm:block px-4 py-2.5 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-xl)] text-sm focus:outline-none focus:ring-2 focus:ring-amber-4 focus:border-amber-6"
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="name">Name</option>
          <option value="size">Size</option>
        </select>

        {/* View mode toggle */}
        <div className="hidden sm:flex bg-[var(--sage-3)] rounded-[var(--radius-xl)] p-1">
          <button
            onClick={() => setViewMode('grid')}
            aria-label="Grid view"
            className={`p-2 rounded-lg transition-colors ${
              viewMode === 'grid'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Grid className="w-4 h-4" />
          </button>
          <button
            onClick={() => setViewMode('list')}
            aria-label="List view"
            className={`p-2 rounded-lg transition-colors ${
              viewMode === 'list'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <List className="w-4 h-4" />
          </button>
        </div>

        {/* Refresh */}
        <button
          onClick={loadVideos}
          aria-label="Refresh videos"
          className="p-2.5 hover:bg-gray-100 rounded-xl text-gray-500 hover:text-gray-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Videos */}
      <div className="flex-1 overflow-y-auto p-3 md:p-4">
        {filteredVideos.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <Film className="w-12 h-12 text-[var(--sage-8)] mb-3" />
            <p className="text-[var(--sage-8)] font-medium">No videos found</p>
            <p className="text-[var(--sage-7)] text-sm mt-1">
              {searchQuery ? 'Try a different search term' : 'Upload a video to get started'}
            </p>
          </div>
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredVideos.map((video) => (
              <VideoCard
                key={video.id}
                id={video.id}
                name={video.original_filename}
                thumbnail={video.thumbnail_url}
                duration={video.duration}
                size={video.file_size}
                uploadedAt={video.uploaded_at ? new Date(video.uploaded_at) : new Date()}
                isProcessed={video.processed ?? false}
                isProcessing={video.processing_status === 'processing'}
                framesAnalyzed={video.frames_analyzed}
                onSelect={() => handleVideoSelect(video)}
                onDelete={() => handleDelete(video.id)}
                isSelected={
                  selectionMode === 'single'
                    ? selectedVideoId === video.id
                    : selectedVideoIds.includes(video.id)
                }
              />
            ))}
          </div>
        ) : (
          // List view
          <div className="space-y-2">
            {filteredVideos.map((video) => (
              <VideoListItem
                key={video.id}
                video={video}
                isSelected={
                  (selectionMode === 'single' && selectedVideoId === video.id) ||
                  (selectionMode === 'multiple' && selectedVideoIds.includes(video.id))
                }
                onSelect={() => handleVideoSelect(video)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer stats */}
      <div className="px-3 md:px-4 py-2 md:py-3 border-t border-[var(--sage-3)] bg-[var(--surface)]/50 backdrop-blur-sm text-sm text-[var(--sage-8)]">
        {filteredVideos.length} video{filteredVideos.length !== 1 ? 's' : ''}
        {searchQuery && ` matching "${searchQuery}"`}
      </div>
    </div>
  );
}
