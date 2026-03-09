'use client';

import React from 'react';
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize,
  SkipBack,
  SkipForward,
} from 'lucide-react';
import { Clip } from '@/lib/api';
import { formatTime } from '@/lib/utils';

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

interface EditorVideoControlsProps {
  isPlaying: boolean;
  isMuted: boolean;
  currentTime: number;
  duration: number;
  clips: Clip[];
  onTogglePlay: () => void;
  onToggleMute: () => void;
  onSeek: (time: number) => void;
  onSkip: (seconds: number) => void;
  onFullscreen: () => void;
}

export function EditorVideoControls({
  isPlaying,
  isMuted,
  currentTime,
  duration,
  clips,
  onTogglePlay,
  onToggleMute,
  onSeek,
  onSkip,
  onFullscreen,
}: EditorVideoControlsProps) {
  const sortedClips = [...clips].sort((a, b) => a.order - b.order);

  return (
    <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4">
      {/* Progress Bar with Clips */}
      <div
        className="relative h-2 bg-white/30 rounded-full mb-3 cursor-pointer group"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const percent = (e.clientX - rect.left) / rect.width;
          onSeek(percent * duration);
        }}
      >
        {/* Clip ranges visualization */}
        {sortedClips.map((clip, idx) => (
          <div
            key={clip.id}
            className={`absolute top-0 h-full ${CLIP_COLORS[idx % CLIP_COLORS.length]} opacity-60 rounded-full`}
            style={{
              left: `${(clip.start_time / duration) * 100}%`,
              width: `${((clip.end_time - clip.start_time) / duration) * 100}%`,
            }}
            title={clip.title || `Clip ${idx + 1}`}
          />
        ))}
        
        {/* Progress */}
        <div
          className="absolute top-0 h-full bg-white rounded-full"
          style={{ width: `${(currentTime / duration) * 100}%` }}
        />
        
        {/* Handle */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full shadow-lg opacity-0 group-hover:opacity-100 transition-opacity"
          style={{ left: `${(currentTime / duration) * 100}%`, marginLeft: '-6px' }}
        />
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            onClick={() => onSkip(-10)}
            className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
          >
            <SkipBack className="w-4 h-4" />
          </button>
          <button
            onClick={onTogglePlay}
            className="p-2 bg-white/20 hover:bg-white/30 rounded-lg text-white transition-colors"
          >
            {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
          </button>
          <button
            onClick={() => onSkip(10)}
            className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
          >
            <SkipForward className="w-4 h-4" />
          </button>
          <span className="text-white text-sm ml-2">
            {formatTime(currentTime)} / {formatTime(duration)}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onToggleMute}
            className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
          >
            {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
          </button>
          <button
            onClick={onFullscreen}
            className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
          >
            <Maximize className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
