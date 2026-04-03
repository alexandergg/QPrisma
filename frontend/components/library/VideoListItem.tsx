'use client';

import React from 'react';
import Image from 'next/image';
import { Film } from 'lucide-react';
import { formatTime, formatFileSize } from '@/lib/utils';

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

interface VideoListItemProps {
  video: Video;
  isSelected: boolean;
  onSelect: () => void;
}

export function VideoListItem({ video, isSelected, onSelect }: VideoListItemProps) {
  return (
    <div
      onClick={onSelect}
      className={`
        flex items-center gap-4 p-4 bg-[var(--surface)] rounded-xl cursor-pointer
        border-2 transition-all hover:shadow-[var(--shadow-md)]
        ${
          isSelected
            ? 'border-[var(--amber-6)] bg-[var(--amber-1)]'
            : 'border-[var(--border)] hover:border-[var(--amber-5)]'
        }
      `}
    >
      {/* Thumbnail */}
      <div className="w-20 h-12 bg-[var(--surface-elevated)] rounded-lg overflow-hidden flex-shrink-0">
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
            <Film className="w-5 h-5 text-[var(--text-tertiary)]" />
          </div>
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="font-medium text-[var(--foreground)] truncate">{video.original_filename}</p>
        <p className="text-sm text-[var(--text-secondary)]">
          {video.duration ? formatTime(video.duration) : ''} •{' '}
          {formatFileSize(video.file_size || 0)}
        </p>
      </div>

      {/* Status */}
      <div className="flex-shrink-0">
        {video.processed ? (
          <span className="text-[var(--sage-8)] text-sm font-medium">Ready</span>
        ) : (
          <span className="text-[var(--amber-8)] text-sm font-medium">Processing</span>
        )}
      </div>
    </div>
  );
}

export type { Video };
