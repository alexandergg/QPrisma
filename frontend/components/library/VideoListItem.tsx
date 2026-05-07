'use client';

import React from 'react';
import Image from 'next/image';
import { CheckCircle, Clock, Eye, Film, HardDrive, Loader2 } from 'lucide-react';
import type { MediaItem } from '@/lib/api';
import { formatDate, formatFileSize, formatTime } from '@/lib/utils';

type Video = MediaItem;

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
            ? 'border-[var(--violet-6)] bg-[var(--violet-1)]'
            : 'border-[var(--border)] hover:border-[var(--violet-5)]'
        }
      `}
    >
      {/* Thumbnail */}
      <div className="relative w-24 h-14 bg-[var(--surface-elevated)] rounded-lg overflow-hidden flex-shrink-0">
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
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--text-secondary)]">
          {video.duration !== undefined && (
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {formatTime(video.duration)}
            </span>
          )}
          <span className="inline-flex items-center gap-1">
            <HardDrive className="w-3 h-3" />
            {formatFileSize(video.file_size || 0)}
          </span>
          <span>{formatDate(video.uploaded_at)}</span>
          {video.frames_analyzed ? (
            <span className="inline-flex items-center gap-1">
              <Eye className="w-3 h-3" />
              {video.frames_analyzed} frames
            </span>
          ) : null}
        </div>
      </div>

      {/* Status */}
      <div className="flex-shrink-0">
        {video.processed ? (
          <span className="inline-flex items-center gap-1.5 text-[var(--sage-8)] text-sm font-medium">
            <CheckCircle className="w-4 h-4" />
            Ready
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-[var(--violet-8)] text-sm font-medium">
            <Loader2 className="w-4 h-4 animate-spin" />
            {video.processing_status === 'queued' ? 'Queued' : 'Processing'}
          </span>
        )}
      </div>
    </div>
  );
}

export type { Video };
