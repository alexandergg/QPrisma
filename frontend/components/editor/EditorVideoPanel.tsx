'use client';

import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react';
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
import SubtitleOverlay, { SubtitleData, SubtitleCue } from './SubtitleOverlay';

interface EditorVideoPanelProps {
  videoUrl?: string;
  videoTitle?: string;
  duration?: number;
  clips?: Clip[];
  currentTime?: number;
  onTimeUpdate?: (time: number) => void;
  onSeek?: (time: number) => void;
  onClipClick?: (clip: Clip) => void;
  activeClipId?: string;
  /** Clip to preview (play from start_time to end_time, then pause) */
  previewClip?: Clip;
  /** Called when preview ends */
  onPreviewEnd?: () => void;
  /** Subtitle data for overlay (from active clip) */
  subtitleData?: SubtitleData;
  /** Whether subtitles are enabled for active clip */
  subtitlesEnabled?: boolean;
  /** Start time of the active clip (for calculating relative time) */
  activeClipStartTime?: number;
  /** Callback when subtitle cue is clicked for editing */
  onSubtitleCueClick?: (cue: SubtitleCue) => void;
}

/**
 * Video Panel for Editor with clips visualization on timeline
 */
export default function EditorVideoPanel({
  videoUrl,
  videoTitle,
  duration = 0,
  clips = [],
  currentTime = 0,
  onTimeUpdate,
  onSeek,
  onClipClick,
  activeClipId,
  previewClip,
  onPreviewEnd,
  subtitleData,
  subtitlesEnabled = false,
  activeClipStartTime = 0,
  onSubtitleCueClick,
}: EditorVideoPanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [localCurrentTime, setLocalCurrentTime] = useState(currentTime);
  const [videoDuration, setVideoDuration] = useState(duration);
  const [isPreviewMode, setIsPreviewMode] = useState(false);
  const previewClipRef = useRef<Clip | undefined>(undefined);

  // Sync external currentTime
  useEffect(() => {
    if (Math.abs(currentTime - localCurrentTime) > 1) {
      setLocalCurrentTime(currentTime);
      if (videoRef.current) {
        videoRef.current.currentTime = currentTime;
      }
    }
  }, [currentTime]);

  // Handle preview clip mode
  useEffect(() => {
    if (previewClip && videoRef.current) {
      // Start preview: seek to start_time and play
      previewClipRef.current = previewClip;
      setIsPreviewMode(true);
      videoRef.current.currentTime = previewClip.start_time;
      videoRef.current.play();
      setIsPlaying(true);
    } else if (!previewClip && isPreviewMode) {
      // Preview cleared
      setIsPreviewMode(false);
      previewClipRef.current = undefined;
    }
  }, [previewClip]);

  // Update duration from video metadata
  const handleLoadedMetadata = useCallback(() => {
    if (videoRef.current) {
      setVideoDuration(videoRef.current.duration);
    }
  }, []);

  const handleTimeUpdate = useCallback(() => {
    if (videoRef.current) {
      const time = videoRef.current.currentTime;
      setLocalCurrentTime(time);
      onTimeUpdate?.(time);

      // Check if we've reached the end of preview clip
      if (isPreviewMode && previewClipRef.current) {
        if (time >= previewClipRef.current.end_time) {
          videoRef.current.pause();
          setIsPlaying(false);
          setIsPreviewMode(false);
          onPreviewEnd?.();
        }
      }
    }
  }, [onTimeUpdate, isPreviewMode, onPreviewEnd]);

  const handleSeek = useCallback((time: number) => {
    if (videoRef.current) {
      const clampedTime = Math.max(0, Math.min(videoDuration, time));
      videoRef.current.currentTime = clampedTime;
      setLocalCurrentTime(clampedTime);
      onSeek?.(clampedTime);
    }
  }, [videoDuration, onSeek]);

  const togglePlay = useCallback(() => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  }, [isPlaying]);

  const toggleMute = useCallback(() => {
    if (videoRef.current) {
      videoRef.current.muted = !isMuted;
      setIsMuted(!isMuted);
    }
  }, [isMuted]);

  const skip = useCallback((seconds: number) => {
    if (videoRef.current) {
      const newTime = Math.max(0, Math.min(videoDuration, videoRef.current.currentTime + seconds));
      handleSeek(newTime);
    }
  }, [videoDuration, handleSeek]);

  const formatTime = (seconds: number): string => {
    if (!seconds || isNaN(seconds)) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Find current clip (if playhead is inside a clip)
  const currentClip = clips.find(
    (c) => localCurrentTime >= c.start_time && localCurrentTime <= c.end_time
  );

  // Calculate subtitle time relative to clip start
  const subtitleRelativeTime = useMemo(() => {
    // If previewing a clip, use previewClip's start time
    if (isPreviewMode && previewClipRef.current) {
      return localCurrentTime - previewClipRef.current.start_time;
    }
    // Otherwise use the provided activeClipStartTime
    return localCurrentTime - activeClipStartTime;
  }, [localCurrentTime, isPreviewMode, activeClipStartTime]);

  // Sort clips by order for display
  const sortedClips = [...clips].sort((a, b) => a.order - b.order);

  // Color palette for clips
  const clipColors = [
    'bg-indigo-500',
    'bg-purple-500',
    'bg-blue-500',
    'bg-cyan-500',
    'bg-teal-500',
    'bg-green-500',
    'bg-amber-500',
    'bg-orange-500',
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Video Title */}
      <div className="px-4 py-3 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 truncate text-sm">
          {videoTitle || 'Source Video'}
        </h3>
      </div>

      {/* Video Player */}
      <div className="relative bg-black aspect-video flex-shrink-0">
        {videoUrl ? (
          <video
            ref={videoRef}
            src={videoUrl}
            className="w-full h-full object-contain"
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={handleLoadedMetadata}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-500">
            <p>No video loaded</p>
          </div>
        )}

        {/* Subtitle Overlay */}
        {subtitlesEnabled && subtitleData && (
          <SubtitleOverlay
            currentTime={subtitleRelativeTime}
            subtitleData={subtitleData}
            enabled={subtitlesEnabled}
            onCueClick={onSubtitleCueClick}
            editMode={!!onSubtitleCueClick}
          />
        )}

        {/* Preview Mode Indicator */}
        {isPreviewMode && previewClipRef.current && (
          <div className="absolute top-3 left-3 right-3 flex items-center justify-between">
            <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-indigo-600/90 backdrop-blur-sm text-white text-sm font-medium rounded-lg shadow-lg">
              <Play className="w-4 h-4 fill-current" />
              Preview: {previewClipRef.current.title || 'Clip'}
              <span className="text-indigo-200">
                ({formatTime(previewClipRef.current.start_time)} - {formatTime(previewClipRef.current.end_time)})
              </span>
            </div>
            <button
              onClick={() => {
                if (videoRef.current) {
                  videoRef.current.pause();
                  setIsPlaying(false);
                }
                setIsPreviewMode(false);
                onPreviewEnd?.();
              }}
              className="px-3 py-1.5 bg-black/50 backdrop-blur-sm text-white text-sm rounded-lg hover:bg-black/70 transition-colors"
            >
              Stop Preview
            </button>
          </div>
        )}

        {/* Video Controls Overlay */}
        {videoUrl && (
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4">
            {/* Progress Bar with Clips */}
            <div
              className="relative h-2 bg-white/30 rounded-full mb-3 cursor-pointer group"
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const percent = (e.clientX - rect.left) / rect.width;
                handleSeek(percent * videoDuration);
              }}
            >
              {/* Clip ranges visualization */}
              {sortedClips.map((clip, idx) => (
                <div
                  key={clip.id}
                  className={`absolute top-0 h-full ${clipColors[idx % clipColors.length]} opacity-60 rounded-full`}
                  style={{
                    left: `${(clip.start_time / videoDuration) * 100}%`,
                    width: `${((clip.end_time - clip.start_time) / videoDuration) * 100}%`,
                  }}
                  title={clip.title || `Clip ${idx + 1}`}
                />
              ))}
              
              {/* Progress */}
              <div
                className="absolute top-0 h-full bg-white rounded-full"
                style={{ width: `${(localCurrentTime / videoDuration) * 100}%` }}
              />
              
              {/* Handle */}
              <div
                className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full shadow-lg opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ left: `${(localCurrentTime / videoDuration) * 100}%`, marginLeft: '-6px' }}
              />
            </div>

            {/* Controls */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => skip(-10)}
                  className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
                >
                  <SkipBack className="w-4 h-4" />
                </button>
                <button
                  onClick={togglePlay}
                  className="p-2 bg-white/20 hover:bg-white/30 rounded-lg text-white transition-colors"
                >
                  {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
                </button>
                <button
                  onClick={() => skip(10)}
                  className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
                >
                  <SkipForward className="w-4 h-4" />
                </button>
                <span className="text-white text-sm ml-2">
                  {formatTime(localCurrentTime)} / {formatTime(videoDuration)}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={toggleMute}
                  className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
                >
                  {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
                </button>
                <button
                  onClick={() => videoRef.current?.requestFullscreen()}
                  className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
                >
                  <Maximize className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Mini Timeline with Clips */}
      {sortedClips.length > 0 && (
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
                    clipColors[idx % clipColors.length]
                  } ${isActive ? 'ring-2 ring-white ring-offset-1 z-10' : 'opacity-80 hover:opacity-100'}`}
                  style={{
                    left: `${(clip.start_time / videoDuration) * 100}%`,
                    width: `${Math.max(((clip.end_time - clip.start_time) / videoDuration) * 100, 1)}%`,
                  }}
                  title={`${clip.title || `Clip ${idx + 1}`} (${formatTime(clip.start_time)} - ${formatTime(clip.end_time)})`}
                >
                  {/* Clip label if wide enough */}
                  {((clip.end_time - clip.start_time) / videoDuration) * 100 > 8 && (
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
              style={{ left: `${(localCurrentTime / videoDuration) * 100}%` }}
            >
              <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-red-500 rounded-full" />
            </div>
          </div>
          
          {/* Time labels */}
          <div className="flex justify-between mt-1 text-xs text-gray-400">
            <span>0:00</span>
            <span>{formatTime(videoDuration)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
