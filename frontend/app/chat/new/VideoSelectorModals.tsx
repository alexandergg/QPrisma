'use client';

import React from 'react';
import { X } from 'lucide-react';
import { VideoGrid } from '@/components/library';
import type { LibraryVideo, VideoData } from '../types';

interface VideoSelectorModalProps {
  isOpen: boolean;
  selectedVideoId?: string;
  onSelectVideo: (video: LibraryVideo) => void;
  onClose: () => void;
}

export function VideoSelectorModal({
  isOpen,
  selectedVideoId,
  onSelectVideo,
  onClose,
}: VideoSelectorModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--surface)] rounded-2xl shadow-2xl w-full max-w-4xl max-h-[80vh] overflow-hidden border border-[var(--border-subtle)]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <h2 className="text-xl font-semibold text-[var(--foreground)]">Select a Video</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-[var(--surface-elevated)] rounded-lg text-[var(--text-secondary)]"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="h-[60vh]">
          <VideoGrid
            onSelectVideo={onSelectVideo}
            selectedVideoId={selectedVideoId}
          />
        </div>
      </div>
    </div>
  );
}

interface MultiVideoSelectorModalProps {
  isOpen: boolean;
  selectedVideos: VideoData[];
  onSelectionChange: (ids: string[]) => void;
  onConfirm: () => void;
  onClose: () => void;
}

export function MultiVideoSelectorModal({
  isOpen,
  selectedVideos,
  onSelectionChange,
  onConfirm,
  onClose,
}: MultiVideoSelectorModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--surface)] rounded-2xl shadow-2xl w-full max-w-4xl max-h-[80vh] overflow-hidden border border-[var(--border-subtle)]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <div>
            <h2 className="text-xl font-semibold text-[var(--foreground)]">Select Multiple Videos</h2>
            <p className="text-sm text-[var(--text-secondary)] mt-1">
              Select up to 10 videos to chat across them. {selectedVideos.length > 0 && `(${selectedVideos.length} selected)`}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-[var(--surface-elevated)] rounded-lg text-[var(--text-secondary)]"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="h-[50vh]">
          <VideoGrid
            selectionMode="multiple"
            selectedVideoIds={selectedVideos.map((v) => v.id)}
            onSelectionChange={onSelectionChange}
          />
        </div>
        <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--border)] bg-[var(--surface-elevated)]">
          <span className="text-sm text-[var(--text-secondary)]">
            {selectedVideos.length === 0
              ? 'No videos selected'
              : `${selectedVideos.length} video${selectedVideos.length !== 1 ? 's' : ''} selected`}
          </span>
          <button
            onClick={onConfirm}
            disabled={selectedVideos.length === 0}
            className="px-6 py-2 bg-gradient-to-r from-purple-500 to-indigo-600 hover:from-purple-600 hover:to-indigo-700 disabled:opacity-50 text-white rounded-xl font-semibold transition-all shadow-lg shadow-purple-500/30"
          >
            {selectedVideos.length > 1 ? `Chat with ${selectedVideos.length} Videos` : 'Confirm Selection'}
          </button>
        </div>
      </div>
    </div>
  );
}
