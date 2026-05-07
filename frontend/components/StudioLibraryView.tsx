'use client';

import React from 'react';
import Image from 'next/image';
import {
  Film,
  Video,
  Search as SearchIcon,
  Play,
  Plus,
  Trash2,
  Grid,
  List,
  ChevronRight,
  Eye,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import type { MediaItem } from '@/lib/api';
import { formatDate, formatFileSize, formatTime } from '@/lib/utils';

export type { MediaItem };

interface StudioLibraryViewProps {
  mediaList: MediaItem[];
  filteredMedia: MediaItem[];
  loadingMedia: boolean;
  searchQuery: string;
  viewMode: 'grid' | 'list';
  processedCount: number;
  pendingCount: number;
  onSearchQueryChange: (query: string) => void;
  onViewModeChange: (mode: 'grid' | 'list') => void;
  onDelete: (e: React.MouseEvent, mediaId: string) => void;
  onShowUpload: () => void;
}

export function StudioLibraryView({
  filteredMedia,
  loadingMedia,
  searchQuery,
  viewMode,
  onSearchQueryChange,
  onViewModeChange,
  onDelete,
  onShowUpload,
}: StudioLibraryViewProps) {
  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-white/70 backdrop-blur-xl border-b border-gray-200/50">
        <div className="max-w-[1600px] mx-auto px-8 py-5">
          <div className="flex items-center justify-between gap-8">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
              <p className="text-sm text-gray-500 mt-0.5">Manage your video library</p>
            </div>

            <div className="flex-1 max-w-xl relative group">
              <SearchIcon className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-indigo-500 transition-colors" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => onSearchQueryChange(e.target.value)}
                placeholder="Search videos..."
                className="w-full pl-12 pr-4 py-3 bg-gray-100 border-2 border-transparent rounded-xl focus:border-indigo-500 focus:bg-white focus:outline-none transition-all text-gray-900 placeholder-gray-400"
              />
            </div>

            <div className="flex items-center gap-2 bg-gray-100 p-1 rounded-lg">
              <button
                onClick={() => onViewModeChange('grid')}
                className={`p-2 rounded-lg transition-all ${viewMode === 'grid' ? 'bg-white text-indigo-600 shadow' : 'text-gray-500 hover:text-gray-700'}`}
              >
                <Grid className="w-5 h-5" />
              </button>
              <button
                onClick={() => onViewModeChange('list')}
                className={`p-2 rounded-lg transition-all ${viewMode === 'list' ? 'bg-white text-indigo-600 shadow' : 'text-gray-500 hover:text-gray-700'}`}
              >
                <List className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Video Grid/List */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-[1600px] mx-auto">
          {loadingMedia ? (
            <div className="flex items-center justify-center py-32">
              <div className="text-center">
                <div className="w-14 h-14 border-4 border-gray-200 border-t-indigo-500 rounded-full animate-spin mx-auto mb-6"></div>
                <p className="text-gray-500 font-medium">Loading your library...</p>
              </div>
            </div>
          ) : filteredMedia.length === 0 ? (
            <EmptyState searchQuery={searchQuery} onShowUpload={onShowUpload} />
          ) : (
            <>
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-semibold text-gray-500">
                    {filteredMedia.length} {filteredMedia.length === 1 ? 'video' : 'videos'}
                  </span>
                </div>
              </div>

              {viewMode === 'grid' ? (
                <MediaGrid media={filteredMedia} onDelete={onDelete} />
              ) : (
                <MediaList media={filteredMedia} onDelete={onDelete} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function EmptyState({ searchQuery, onShowUpload }: { searchQuery: string; onShowUpload: () => void }) {
  return (
    <div className="flex items-center justify-center py-32">
      <div className="text-center max-w-md">
        <div className="bg-gradient-to-br from-indigo-100 to-purple-100 rounded-3xl w-28 h-28 flex items-center justify-center mx-auto mb-8 shadow-xl shadow-indigo-200/50">
          <Video className="w-12 h-12 text-indigo-500" />
        </div>
        <h3 className="text-2xl font-bold text-gray-900 mb-3">
          {searchQuery ? 'No videos found' : 'Start your journey'}
        </h3>
        <p className="text-gray-500 mb-8 leading-relaxed">
          {searchQuery
            ? 'Try adjusting your search terms'
            : 'Upload your first video to unlock AI-powered insights and analytics.'
          }
        </p>
        {!searchQuery && (
          <button
            onClick={onShowUpload}
            className="px-8 py-4 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl transition-all font-semibold flex items-center gap-2 mx-auto shadow-lg shadow-indigo-500/30 hover:shadow-xl hover:shadow-indigo-500/40 hover:-translate-y-0.5"
          >
            <Plus className="w-5 h-5" />
            Upload Video
          </button>
        )}
      </div>
    </div>
  );
}

function MediaGrid({ media, onDelete }: { media: MediaItem[]; onDelete: (e: React.MouseEvent, id: string) => void }) {
  const router = useRouter();

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-6">
      {media.map((item) => (
        <div
          key={item.id}
          onClick={() => router.push(`/chat?videoId=${item.id}`)}
          className="group cursor-pointer bg-white rounded-2xl shadow-lg shadow-gray-200/50 border border-gray-100 overflow-hidden hover:shadow-xl hover:shadow-indigo-200/30 hover:-translate-y-1 transition-all duration-300"
        >
          {/* Thumbnail */}
          <div className="aspect-video bg-gradient-to-br from-gray-100 to-gray-200 relative overflow-hidden">
            {item.thumbnail_url ? (
              <Image src={item.thumbnail_url} alt={item.original_filename} fill sizes="(min-width: 1536px) 25vw, (min-width: 1024px) 33vw, (min-width: 768px) 50vw, 100vw" className="object-cover" />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <Film className="w-12 h-12 text-gray-300" />
              </div>
            )}

            <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all duration-300 bg-gradient-to-t from-black/60 via-black/20 to-transparent">
              <div className="bg-white text-indigo-600 rounded-full p-4 transform scale-90 group-hover:scale-100 transition-transform duration-300 shadow-xl">
                <Play className="w-6 h-6 fill-indigo-600" />
              </div>
            </div>

            {/* Status badge */}
            <div className="absolute top-3 left-3">
              {item.processed ? (
                <div className="px-2.5 py-1 bg-green-500 text-white text-xs font-bold rounded-full shadow-lg flex items-center gap-1">
                  <div className="w-1.5 h-1.5 bg-white rounded-full"></div>
                  Ready
                </div>
              ) : (
                <div className="px-2.5 py-1 bg-violet-500 text-white text-xs font-bold rounded-full shadow-lg flex items-center gap-1 animate-pulse">
                  <div className="w-1.5 h-1.5 bg-white rounded-full"></div>
                  Processing
                </div>
              )}
            </div>

            {/* Duration badge */}
            {item.duration && (
              <div className="absolute bottom-3 right-3">
                <div className="px-2 py-1 bg-black/70 backdrop-blur text-white text-xs font-bold rounded-lg">
                  {formatTime(item.duration)}
                </div>
              </div>
            )}
          </div>

          {/* Info */}
          <div className="p-4">
            <div className="flex justify-between items-start mb-2">
              <h3 className="font-semibold text-gray-900 truncate pr-3 group-hover:text-indigo-600 transition-colors">
                {item.original_filename}
              </h3>
              <button
                onClick={(e) => onDelete(e, item.id)}
                className="text-gray-400 hover:text-red-500 transition-colors p-1 hover:bg-red-50 rounded-lg"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>

            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span>{formatDate(item.uploaded_at)}</span>
              <span className="w-1 h-1 rounded-full bg-gray-300"></span>
              <span>{formatFileSize(item.file_size)}</span>
            </div>

            {item.frames_analyzed && (
              <div className="mt-3 flex items-center gap-2 text-xs font-medium text-indigo-600 bg-indigo-50 px-2 py-1 rounded-lg w-fit">
                <Eye className="w-3 h-3" />
                {item.frames_analyzed} frames analyzed
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function MediaList({ media, onDelete }: { media: MediaItem[]; onDelete: (e: React.MouseEvent, id: string) => void }) {
  const router = useRouter();

  return (
    <div className="space-y-3">
      {media.map((item) => (
        <div
          key={item.id}
          onClick={() => router.push(`/chat?videoId=${item.id}`)}
          className="group cursor-pointer bg-white rounded-xl shadow-lg shadow-gray-200/50 border border-gray-100 overflow-hidden hover:shadow-xl hover:shadow-indigo-200/30 transition-all duration-300 flex items-center gap-4 p-4"
        >
          {/* Thumbnail */}
          <div className="w-32 h-20 bg-gradient-to-br from-gray-100 to-gray-200 rounded-lg relative overflow-hidden flex-shrink-0">
            {item.thumbnail_url ? (
              <Image src={item.thumbnail_url} alt={item.original_filename} fill sizes="128px" className="object-cover" />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <Film className="w-8 h-8 text-gray-300" />
              </div>
            )}
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-gray-900 truncate group-hover:text-indigo-600 transition-colors">
              {item.original_filename}
            </h3>
            <div className="flex items-center gap-2 text-sm text-gray-500 mt-1">
              <span>{formatDate(item.uploaded_at)}</span>
              <span className="w-1 h-1 rounded-full bg-gray-300"></span>
              <span>{formatFileSize(item.file_size)}</span>
              {item.duration && (
                <>
                  <span className="w-1 h-1 rounded-full bg-gray-300"></span>
                  <span>{formatTime(item.duration)}</span>
                </>
              )}
            </div>
          </div>

          {/* Status */}
          <div className="flex items-center gap-4">
            {item.processed ? (
              <div className="px-3 py-1.5 bg-green-100 text-green-700 text-xs font-bold rounded-full">
                Ready
              </div>
            ) : (
              <div className="px-3 py-1.5 bg-violet-100 text-violet-700 text-xs font-bold rounded-full animate-pulse">
                Processing
              </div>
            )}

            <button
              onClick={(e) => onDelete(e, item.id)}
              className="text-gray-400 hover:text-red-500 transition-colors p-2 hover:bg-red-50 rounded-lg"
            >
              <Trash2 className="w-4 h-4" />
            </button>

            <ChevronRight className="w-5 h-5 text-gray-400 group-hover:text-indigo-500 group-hover:translate-x-1 transition-all" />
          </div>
        </div>
      ))}
    </div>
  );
}
