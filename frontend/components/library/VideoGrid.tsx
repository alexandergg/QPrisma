'use client';

import React, { useState, useEffect } from 'react';
import Image from 'next/image';
import { Search, Grid, List, Film, Loader2, RefreshCw } from 'lucide-react';
import VideoCard from './VideoCard';
import { apiClient } from '@/lib/api';

interface Video {
  id: string;
  original_filename: string;
  media_type?: string;
  file_size?: number;
  uploaded_at?: string;
  processed?: boolean;
  processing_status?: string;
  duration?: number;
  frames_analyzed?: number;
  thumbnail_url?: string;
}

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

  // Load videos
  useEffect(() => {
    loadVideos();
  }, []);

  const loadVideos = async () => {
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
  };

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

  const handleVideoSelect = (video: Video) => {
    if (selectionMode === 'single') {
      onSelectVideo?.(video);
    } else {
      const isSelected = selectedVideoIds.includes(video.id);
      const newSelection = isSelected
        ? selectedVideoIds.filter((id) => id !== video.id)
        : [...selectedVideoIds, video.id];
      onSelectionChange?.(newSelection);
    }
  };

  const handleDelete = async (videoId: string) => {
    if (!confirm('Are you sure you want to delete this video?')) return;

    try {
      await apiClient.deleteMedia(videoId);
      setVideos((prev) => prev.filter((v) => v.id !== videoId));
      onDeleteVideo?.(videoId);
    } catch (err) {
      console.error('Failed to delete video:', err);
      alert('Failed to delete video');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-indigo-500 animate-spin mx-auto mb-3" />
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
          <button
            onClick={loadVideos}
            className="px-4 py-2 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 flex items-center gap-2 mx-auto"
          >
            <RefreshCw className="w-4 h-4" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-4 p-4 border-b border-gray-100 bg-white/50 backdrop-blur-sm">
        {/* Search */}
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search videos..."
            className="w-full pl-10 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300"
          />
        </div>

        {/* Sort */}
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortOption)}
          className="px-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300"
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="name">Name</option>
          <option value="size">Size</option>
        </select>

        {/* View mode toggle */}
        <div className="flex bg-gray-100 rounded-xl p-1">
          <button
            onClick={() => setViewMode('grid')}
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
          className="p-2.5 hover:bg-gray-100 rounded-xl text-gray-500 hover:text-gray-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Videos */}
      <div className="flex-1 overflow-y-auto p-4">
        {filteredVideos.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <Film className="w-12 h-12 text-gray-300 mb-3" />
            <p className="text-gray-500 font-medium">No videos found</p>
            <p className="text-gray-400 text-sm mt-1">
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
              <div
                key={video.id}
                onClick={() => handleVideoSelect(video)}
                className={`
                  flex items-center gap-4 p-4 bg-white rounded-xl cursor-pointer
                  border-2 transition-all hover:shadow-md
                  ${
                    (selectionMode === 'single' && selectedVideoId === video.id) ||
                    (selectionMode === 'multiple' && selectedVideoIds.includes(video.id))
                      ? 'border-indigo-500 bg-indigo-50/50'
                      : 'border-transparent hover:border-indigo-200'
                  }
                `}
              >
                {/* Thumbnail */}
                <div className="w-20 h-12 bg-gray-100 rounded-lg overflow-hidden flex-shrink-0">
                    {video.thumbnail_url ? (
                      <Image
                        src={video.thumbnail_url}
                        alt={video.original_filename}
                        fill
                        sizes="80px"
                        className="object-cover"
                      />
                    ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <Film className="w-5 h-5 text-gray-300" />
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-gray-900 truncate">{video.original_filename}</p>
                  <p className="text-sm text-gray-500">
                    {video.duration ? formatDuration(video.duration) : ''} •{' '}
                    {formatSize(video.file_size || 0)}
                  </p>
                </div>

                {/* Status */}
                <div className="flex-shrink-0">
                    {video.processed ? (
                      <span className="text-green-600 text-sm font-medium">Ready</span>
                    ) : (
                      <span className="text-indigo-600 text-sm font-medium">Processing</span>
                    )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer stats */}
      <div className="px-4 py-3 border-t border-gray-100 bg-white/50 backdrop-blur-sm text-sm text-gray-500">
        {filteredVideos.length} video{filteredVideos.length !== 1 ? 's' : ''}
        {searchQuery && ` matching "${searchQuery}"`}
      </div>
    </div>
  );
}

// Helper functions
function formatDuration(seconds: number): string {
  if (!seconds || isNaN(seconds)) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}
