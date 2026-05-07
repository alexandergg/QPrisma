'use client';

import React from 'react';
import {
  AlertCircle,
  CalendarDays,
  CheckCircle,
  Clock,
  Eye,
  Film,
  HardDrive,
  Loader2,
} from 'lucide-react';
import type { MediaItem } from '@/lib/api';
import { formatDate, formatFileSize, formatTime } from '@/lib/utils';

type Video = MediaItem;
type VideoStatus = 'ready' | 'queued' | 'processing' | 'failed' | 'pending';

interface VideoStatusView {
  label: string;
  icon: typeof CheckCircle;
  className: string;
  isActive: boolean;
}

interface VideoListItemProps {
  video: Video;
  isSelected: boolean;
  onSelect: () => void;
}

function getVideoStatus(video: Video): VideoStatus {
  const processingStatus = video.processing_status?.toLowerCase();

  if (video.processed === true || processingStatus === 'completed' || processingStatus === 'ready') {
    return 'ready';
  }

  if (processingStatus === 'queued') {
    return 'queued';
  }

  if (processingStatus === 'processing' || processingStatus === 'running') {
    return 'processing';
  }

  if (processingStatus === 'failed' || processingStatus === 'error') {
    return 'failed';
  }

  return 'pending';
}

function getVideoStatusView(status: VideoStatus): VideoStatusView {
  switch (status) {
    case 'ready':
      return {
        label: 'Ready',
        icon: CheckCircle,
        className: 'bg-[var(--sage-3)] text-[var(--sage-8)]',
        isActive: false,
      };
    case 'queued':
      return {
        label: 'Queued',
        icon: Clock,
        className: 'bg-[var(--surface-elevated)] text-[var(--text-secondary)]',
        isActive: false,
      };
    case 'processing':
      return {
        label: 'Processing',
        icon: Loader2,
        className: 'bg-[var(--violet-3)] text-[var(--violet-11)]',
        isActive: true,
      };
    case 'failed':
      return {
        label: 'Failed',
        icon: AlertCircle,
        className: 'bg-red-50 text-red-700',
        isActive: false,
      };
    default:
      return {
        label: 'Pending',
        icon: Clock,
        className: 'bg-[var(--surface-elevated)] text-[var(--text-secondary)]',
        isActive: false,
      };
  }
}

export function VideoListItem({ video, isSelected, onSelect }: VideoListItemProps) {
  const statusView = getVideoStatusView(getVideoStatus(video));
  const StatusIcon = statusView.icon;

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
      <div className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--violet-2)] to-[var(--sage-2)] text-[var(--violet-8)] ring-1 ring-[var(--border-subtle)]">
        <Film className="h-6 w-6" aria-hidden="true" />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="font-medium text-[var(--foreground)] truncate">{video.original_filename}</p>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--text-secondary)]">
          {video.duration !== undefined && (
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3 h-3" aria-hidden="true" />
              {formatTime(video.duration)}
            </span>
          )}
          <span className="inline-flex items-center gap-1">
            <HardDrive className="w-3 h-3" aria-hidden="true" />
            {formatFileSize(video.file_size || 0)}
          </span>
          <span className="inline-flex items-center gap-1">
            <CalendarDays className="w-3 h-3" aria-hidden="true" />
            {formatDate(video.uploaded_at)}
          </span>
          {video.frames_analyzed ? (
            <span className="inline-flex items-center gap-1">
              <Eye className="w-3 h-3" aria-hidden="true" />
              {video.frames_analyzed} frames
            </span>
          ) : null}
        </div>
      </div>

      {/* Status */}
      <div className="flex-shrink-0">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm font-medium ${statusView.className}`}
        >
          <StatusIcon
            className={`w-4 h-4 ${statusView.isActive ? 'animate-spin' : ''}`}
            aria-hidden="true"
          />
          {statusView.label}
        </span>
      </div>
    </div>
  );
}

export type { Video };
