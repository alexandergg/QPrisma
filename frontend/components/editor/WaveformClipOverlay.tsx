'use client';

import React from 'react';
import { Clip } from '@/lib/api';
import { formatTime } from '@/lib/utils';

interface WaveformClipOverlayProps {
  clips: Clip[];
  duration: number;
  activeClipId?: string;
  clipColors: { bg: string; border: string }[];
  dragState: {
    clipId: string;
    edge: 'start' | 'end';
  } | null;
  onClipClick?: (clip: Clip) => void;
  onDragStart: (
    e: React.MouseEvent,
    clipId: string,
    edge: 'start' | 'end',
    initialTime: number
  ) => void;
}

export function WaveformClipOverlay({
  clips,
  duration,
  activeClipId,
  clipColors,
  dragState,
  onClipClick,
  onDragStart,
}: WaveformClipOverlayProps) {
  const sortedClips = [...clips].sort((a, b) => a.start_time - b.start_time);

  return (
    <div 
      className="relative h-full"
      style={{ 
        width: `100%`,
        minWidth: '100%',
      }}
    >
      {sortedClips.map((clip, idx) => {
        const isActive = activeClipId === clip.id;
        const color = clipColors[idx % clipColors.length];
        const leftPercent = (clip.start_time / duration) * 100;
        const widthPercent = ((clip.end_time - clip.start_time) / duration) * 100;

        return (
          <div
            key={clip.id}
            className={`absolute top-0 bottom-0 transition-all pointer-events-auto ${
              isActive ? 'z-10' : 'z-0'
            }`}
            style={{
              left: `${leftPercent}%`,
              width: `${Math.max(widthPercent, 0.5)}%`,
              backgroundColor: color.bg,
              borderTop: `3px solid ${color.border}`,
              borderBottom: `3px solid ${color.border}`,
              boxShadow: isActive ? `0 0 0 2px ${color.border}` : undefined,
            }}
            onClick={() => onClipClick?.(clip)}
          >
            {/* Clip label */}
            <div className="absolute top-1 left-1 right-1 flex items-center justify-between">
              <span 
                className="text-xs font-medium truncate px-1 py-0.5 rounded"
                style={{ 
                  backgroundColor: color.border,
                  color: 'white',
                }}
              >
                {clip.title || `Clip ${idx + 1}`}
              </span>
              <span className="text-xs text-gray-600 bg-white/80 px-1 rounded">
                {formatTime(clip.end_time - clip.start_time)}
              </span>
            </div>

            {/* Left handle (start time) */}
            <div
              className={`absolute left-0 top-0 bottom-0 w-2 cursor-ew-resize group ${
                dragState?.clipId === clip.id && dragState?.edge === 'start' 
                  ? 'bg-white/50' 
                  : 'hover:bg-white/30'
              }`}
              onMouseDown={(e) => onDragStart(e, clip.id, 'start', clip.start_time)}
              style={{ borderLeft: `2px solid ${color.border}` }}
            >
              <div className="absolute inset-y-0 left-0 w-1 flex items-center justify-center">
                <div className="w-0.5 h-8 bg-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            </div>

            {/* Right handle (end time) */}
            <div
              className={`absolute right-0 top-0 bottom-0 w-2 cursor-ew-resize group ${
                dragState?.clipId === clip.id && dragState?.edge === 'end'
                  ? 'bg-white/50'
                  : 'hover:bg-white/30'
              }`}
              onMouseDown={(e) => onDragStart(e, clip.id, 'end', clip.end_time)}
              style={{ borderRight: `2px solid ${color.border}` }}
            >
              <div className="absolute inset-y-0 right-0 w-1 flex items-center justify-center">
                <div className="w-0.5 h-8 bg-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
