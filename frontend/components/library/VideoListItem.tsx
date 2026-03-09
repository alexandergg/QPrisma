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
        flex items-center gap-4 p-4 bg-white rounded-xl cursor-pointer
        border-2 transition-all hover:shadow-md
        ${
          isSelected
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
          {video.duration ? formatTime(video.duration) : ''} •{' '}
          {formatFileSize(video.file_size || 0)}
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
  );
}

export type { Video };
