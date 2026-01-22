'use client';

import React from 'react';
import {
  Play,
  Trash2,
  GripVertical,
  Star,
  Subtitles,
  Download,
  Clock,
  Sparkles,
} from 'lucide-react';
import { Clip } from '@/lib/api';

interface ClipCardProps {
  clip: Clip;
  index: number;
  isActive?: boolean;
  onClick?: () => void;
  onPlay?: () => void;
  onDelete?: () => void;
  onSubtitlesToggle?: () => void;
  onExport?: () => void;
  isDragging?: boolean;
}

/**
 * Individual clip card for the clips list
 */
export default function ClipCard({
  clip,
  index,
  isActive = false,
  onClick,
  onPlay,
  onDelete,
  onSubtitlesToggle,
  onExport,
  isDragging = false,
}: ClipCardProps) {
  const formatTime = (seconds: number): string => {
    if (!seconds || isNaN(seconds)) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const duration = clip.end_time - clip.start_time;

  // Color based on viral score
  const getViralScoreColor = (score: number | undefined) => {
    if (!score) return 'text-gray-400';
    if (score >= 80) return 'text-green-500';
    if (score >= 60) return 'text-yellow-500';
    if (score >= 40) return 'text-orange-500';
    return 'text-red-400';
  };

  const getExportStatusBadge = () => {
    switch (clip.export_status) {
      case 'done':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-green-100 text-green-700 rounded text-xs">
            <Download className="w-3 h-3" />
            Ready
          </span>
        );
      case 'processing':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-xs animate-pulse">
            Exporting...
          </span>
        );
      case 'error':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-xs">
            Error
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <div
      onClick={onClick}
      className={`group relative p-3 rounded-xl border transition-all cursor-pointer ${
        isActive
          ? 'bg-indigo-50 border-indigo-300 shadow-sm'
          : 'bg-white border-gray-200 hover:border-indigo-200 hover:bg-gray-50'
      } ${isDragging ? 'shadow-lg ring-2 ring-indigo-400' : ''}`}
    >
      {/* Drag Handle */}
      <div className="absolute left-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab">
        <GripVertical className="w-4 h-4 text-gray-400" />
      </div>

      <div className="flex items-start gap-3 pl-4">
        {/* Clip Number/Play Button */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onPlay?.();
          }}
          className={`flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center transition-all ${
            isActive
              ? 'bg-indigo-500 text-white'
              : 'bg-gray-100 text-gray-600 group-hover:bg-indigo-100 group-hover:text-indigo-600'
          }`}
        >
          <Play className="w-4 h-4 fill-current" />
        </button>

        {/* Clip Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-900 truncate">
              {clip.title || `Clip ${index + 1}`}
            </span>
            {clip.is_ai_suggested && (
              <span title="AI Suggested">
                <Sparkles className="w-3.5 h-3.5 text-purple-500" />
              </span>
            )}
            {getExportStatusBadge()}
          </div>

          <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
            {/* Time range */}
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {formatTime(clip.start_time)} - {formatTime(clip.end_time)}
            </span>

            {/* Duration */}
            <span className="text-gray-400">
              ({formatTime(duration)})
            </span>

            {/* Viral Score */}
            {clip.viral_score !== undefined && clip.viral_score > 0 && (
              <span className={`inline-flex items-center gap-1 ${getViralScoreColor(clip.viral_score)}`}>
                <Star className="w-3 h-3 fill-current" />
                {Math.round(clip.viral_score)}
              </span>
            )}

            {/* Subtitles indicator */}
            {clip.subtitles_enabled && (
              <span className="inline-flex items-center gap-1 text-indigo-500">
                <Subtitles className="w-3 h-3" />
                {clip.subtitle_style || 'On'}
              </span>
            )}
          </div>

          {/* Viral reasons */}
          {clip.viral_reasons && clip.viral_reasons.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {clip.viral_reasons.slice(0, 3).map((reason, i) => (
                <span
                  key={i}
                  className="px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded text-xs"
                >
                  {reason}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {onSubtitlesToggle && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onSubtitlesToggle();
              }}
              className={`p-1.5 rounded-lg transition-colors ${
                clip.subtitles_enabled
                  ? 'bg-indigo-100 text-indigo-600'
                  : 'hover:bg-gray-100 text-gray-400 hover:text-gray-600'
              }`}
              title={clip.subtitles_enabled ? 'Disable subtitles' : 'Enable subtitles'}
            >
              <Subtitles className="w-4 h-4" />
            </button>
          )}

          {onExport && clip.export_status !== 'processing' && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onExport();
              }}
              className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-colors"
              title="Export clip"
            >
              <Download className="w-4 h-4" />
            </button>
          )}

          {onDelete && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="p-1.5 hover:bg-red-50 rounded-lg text-gray-400 hover:text-red-500 transition-colors"
              title="Delete clip"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
