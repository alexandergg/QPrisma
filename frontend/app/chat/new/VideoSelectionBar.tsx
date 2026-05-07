'use client';

import React from 'react';
import { X, Film, Library } from 'lucide-react';
import type { VideoData } from '../types';

interface VideoSelectionBarProps {
  selectedVideo: VideoData | null;
  selectedVideos: VideoData[];
  isMultiVideo: boolean;
  currentMode: 'single' | 'library';
  onRemoveVideo: (videoId: string) => void;
  onClearVideo: () => void;
  onChangeVideo: () => void;
  onAddMoreVideos: () => void;
  onEditSelection: () => void;
}

export default function VideoSelectionBar({
  selectedVideo,
  selectedVideos,
  isMultiVideo,
  currentMode,
  onRemoveVideo,
  onClearVideo,
  onChangeVideo,
  onAddMoreVideos,
  onEditSelection,
}: VideoSelectionBarProps) {
  if (!selectedVideo && !isMultiVideo) return null;

  return (
    <div className="flex items-center gap-3 px-4 py-3 bg-[var(--surface)]/80 backdrop-blur-sm border-b border-[var(--border-subtle)]">
      {isMultiVideo ? (
        <>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-purple-50 dark:bg-purple-500/15 text-purple-700 dark:text-purple-300 rounded-full">
            <Library className="w-4 h-4" />
            <span className="text-sm font-medium">
              {selectedVideos.length} videos selected
            </span>
          </div>
          <div className="flex items-center gap-1 overflow-x-auto max-w-[40%] md:max-w-[60%]">
            {selectedVideos.map((v) => (
              <div
                key={v.id}
                className="flex items-center gap-1 px-2 py-1 bg-indigo-50 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 rounded-full text-xs whitespace-nowrap"
              >
                <Film className="w-3 h-3" />
                <span className="max-w-[120px] truncate">{v.title}</span>
                <button
                  onClick={() => onRemoveVideo(v.id)}
                  className="p-0.5 hover:bg-indigo-100 dark:hover:bg-indigo-500/25 rounded-full"
                  aria-label={`Remove ${v.title}`}
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
          <button
            onClick={onEditSelection}
            className="text-sm text-[var(--text-secondary)] hover:text-purple-600 dark:hover:text-purple-400"
          >
            Edit selection
          </button>
        </>
      ) : selectedVideo && currentMode === 'single' ? (
        <>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-indigo-50 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 rounded-full">
            <Film className="w-4 h-4" />
            <span className="text-sm font-medium truncate max-w-[200px]">
              {selectedVideo.title}
            </span>
            <button
              onClick={onClearVideo}
              className="p-0.5 hover:bg-indigo-100 dark:hover:bg-indigo-500/25 rounded-full"
              aria-label={`Clear ${selectedVideo.title}`}
            >
              <X className="w-3 h-3" />
            </button>
          </div>
          <button
            onClick={onChangeVideo}
            className="text-sm text-[var(--text-secondary)] hover:text-indigo-600 dark:hover:text-indigo-400"
          >
            Change video
          </button>
          <button
            onClick={onAddMoreVideos}
            className="text-sm text-[var(--text-secondary)] hover:text-purple-600 dark:hover:text-purple-400 ml-1"
          >
            + Add more videos
          </button>
        </>
      ) : null}
    </div>
  );
}
