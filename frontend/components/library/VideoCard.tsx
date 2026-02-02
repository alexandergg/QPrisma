'use client';

import React, { memo } from 'react';
import Image from 'next/image';
import { Play, Clock, Film, CheckCircle, Loader2, MoreVertical, Trash2 } from 'lucide-react';
import { formatTime, formatFileSize, formatDate } from '@/lib/utils';

interface VideoCardProps {
  id: string;
  name: string;
  thumbnail?: string;
  duration?: number;
  size?: number;
  uploadedAt: Date;
  isProcessed: boolean;
  isProcessing?: boolean;
  framesAnalyzed?: number;
  onSelect?: () => void;
  onDelete?: () => void;
  isSelected?: boolean;
}

function VideoCard({
  name,
  thumbnail,
  duration,
  size,
  uploadedAt,
  isProcessed,
  isProcessing = false,
  framesAnalyzed,
  onSelect,
  onDelete,
  isSelected = false,
}: VideoCardProps) {
  const [showMenu, setShowMenu] = React.useState(false);

  return (
    <div
      onClick={onSelect}
      className={`
        group relative bg-white rounded-2xl overflow-hidden cursor-pointer
        border-2 transition-all duration-200
        shadow-lg shadow-gray-200/50 hover:shadow-xl hover:shadow-indigo-200/30
        ${isSelected ? 'border-indigo-500 ring-4 ring-indigo-100' : 'border-transparent hover:border-indigo-200'}
      `}
    >
      {/* Thumbnail */}
      <div className="relative aspect-video bg-gray-100">
        {thumbnail ? (
          <Image src={thumbnail} alt={name} fill sizes="100vw" className="object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Film className="w-12 h-12 text-gray-300" />
          </div>
        )}

        {/* Overlay on hover */}
        <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
          <div className="w-14 h-14 rounded-full bg-white/90 flex items-center justify-center shadow-lg">
            <Play className="w-6 h-6 text-indigo-600 fill-indigo-600 ml-1" />
          </div>
        </div>

        {/* Duration badge */}
        {duration !== undefined && (
          <div className="absolute bottom-2 right-2 bg-black/70 text-white text-xs font-mono px-2 py-1 rounded-md">
            {formatTime(duration)}
          </div>
        )}

        {/* Processing indicator */}
        {isProcessing && (
          <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
            <div className="bg-white rounded-xl px-4 py-2 flex items-center gap-2 shadow-lg">
              <Loader2 className="w-4 h-4 text-indigo-600 animate-spin" />
              <span className="text-sm font-medium text-gray-700">Processing...</span>
            </div>
          </div>
        )}

        {/* Selected indicator */}
        {isSelected && (
          <div className="absolute top-2 left-2 bg-indigo-500 text-white p-1.5 rounded-lg shadow-lg">
            <CheckCircle className="w-4 h-4" />
          </div>
        )}
      </div>

      {/* Info */}
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-gray-900 truncate group-hover:text-indigo-600 transition-colors">
              {name}
            </h3>
            <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
              {size !== undefined && <span>{formatFileSize(size)}</span>}
              <span>•</span>
              <span>{formatDate(uploadedAt)}</span>
            </div>
          </div>

          {/* Menu button */}
          <div className="relative">
            <button
              onClick={(e) => {
                e.stopPropagation();
                setShowMenu(!showMenu);
              }}
              className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-colors opacity-0 group-hover:opacity-100"
            >
              <MoreVertical className="w-4 h-4" />
            </button>

            {/* Dropdown menu */}
            {showMenu && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowMenu(false);
                  }}
                />
                <div className="absolute right-0 top-8 z-20 bg-white rounded-xl shadow-xl border border-gray-100 py-1 min-w-[140px]">
                  {onDelete && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setShowMenu(false);
                        onDelete();
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
                    >
                      <Trash2 className="w-4 h-4" />
                      Delete
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Status */}
        <div className="mt-3 flex items-center gap-2">
          {isProcessed ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-green-50 text-green-700 text-xs font-medium rounded-full">
              <CheckCircle className="w-3 h-3" />
              Ready
              {framesAnalyzed && <span className="text-green-600">• {framesAnalyzed} frames</span>}
            </span>
          ) : isProcessing ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-indigo-50 text-indigo-700 text-xs font-medium rounded-full">
              <Loader2 className="w-3 h-3 animate-spin" />
              Processing
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-gray-100 text-gray-600 text-xs font-medium rounded-full">
              <Clock className="w-3 h-3" />
              Pending
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default memo(VideoCard);
