'use client';

import React from 'react';
import { Play } from 'lucide-react';
import { Clip } from '@/lib/api';
import { formatTime } from '@/lib/utils';

interface ClipsTimelineProps {
  clips: Clip[];
  duration: number;
  currentTime: number;
  activeClipId?: string;
  currentClip?: Clip;
  onClipClick?: (clip: Clip) => void;
}

const CLIP_COLORS = [
  'bg-indigo-500',
  'bg-purple-500',
  'bg-blue-500',
  'bg-cyan-500',
  'bg-teal-500',
  'bg-green-500',
  'bg-amber-500',
  'bg-orange-500',
];

export function ClipsTimeline({
  clips,
  duration,
  currentTime,
  activeClipId,
  currentClip,
  onClipClick,
}: ClipsTimelineProps) {
  const sortedClips = [...clips].sort((a, b) => a.order - b.order);

  return (
    <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 uppercase">
          Clips Timeline ({sortedClips.length})
        </span>
        {currentClip && (
          <span className="text-xs text-indigo-600 font-medium">
            Playing: {currentClip.title || `Clip ${sortedClips.findIndex(c => c.id === currentClip.id) + 1}`}
          </span>
        )}
      </div>

      {/* Visual timeline bar */}
      <div className="relative h-6 bg-gray-200 rounded-lg overflow-hidden">
        {/* Time marks */}
        <div className="absolute inset-0 flex">
          {[0, 0.25, 0.5, 0.75].map((pos) => (
            <div
              key={pos}
              className="absolute top-0 bottom-0 border-l border-gray-300"
              style={{ left: `${pos * 100}%` }}
            />
          ))}
        </div>

        {/* Clips */}
        {sortedClips.map((clip, idx) => {
          const isActive = activeClipId === clip.id || currentClip?.id === clip.id;

          return (
            <div
              key={clip.id}
              onClick={() => onClipClick?.(clip)}
              className={`absolute top-0.5 bottom-0.5 rounded cursor-pointer transition-all ${
                CLIP_COLORS[idx % CLIP_COLORS.length]
              } ${isActive ? 'ring-2 ring-white ring-offset-1 z-10' : 'opacity-80 hover:opacity-100'}`}
              style={{
                left: `${(clip.start_time / duration) * 100}%`,
                width: `${Math.max(((clip.end_time - clip.start_time) / duration) * 100, 1)}%`,
              }}
              title={`${clip.title || `Clip ${idx + 1}`} (${formatTime(clip.start_time)} - ${formatTime(clip.end_time)})`}
            >
              {((clip.end_time - clip.start_time) / duration) * 100 > 8 && (
                <span className="absolute inset-0 flex items-center justify-center text-white text-xs font-medium truncate px-1">
                  {idx + 1}
                </span>
              )}
            </div>
          );
        })}

        {/* Playhead */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-red-500 z-20"
          style={{ left: `${(currentTime / duration) * 100}%` }}
        >
          <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-red-500 rounded-full" />
        </div>
      </div>

      {/* Time labels */}
      <div className="flex justify-between mt-1 text-xs text-gray-400">
        <span>0:00</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}
