'use client';

import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { Play } from 'lucide-react';
import { Clip } from '@/lib/api';
import { formatTime } from '@/lib/utils';
import SubtitleOverlay, { SubtitleData, SubtitleCue } from './SubtitleOverlay';
import { ClipsTimeline } from './ClipsTimeline';
import { EditorVideoControls } from './EditorVideoControls';

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
  const [previewClipState, setPreviewClipState] = useState<Clip | null>(null);

  // Sync external currentTime
  useEffect(() => {
    if (Math.abs(currentTime - localCurrentTime) > 1) {
      if (videoRef.current) {
        videoRef.current.currentTime = currentTime;
      }
    }
  }, [currentTime, localCurrentTime]);

  // Handle preview clip mode
  useEffect(() => {
    if (previewClip && videoRef.current) {
      // Start preview: seek to start_time and play
      previewClipRef.current = previewClip;
      Promise.resolve().then(() => {
        setPreviewClipState(previewClip);
        setIsPreviewMode(true);
        if (videoRef.current) {
          videoRef.current.currentTime = previewClip.start_time;
          videoRef.current.play();
        }
        setIsPlaying(true);
      });
    } else if (!previewClip && isPreviewMode) {
      // Preview cleared
      Promise.resolve().then(() => {
        setIsPreviewMode(false);
        previewClipRef.current = undefined;
        setPreviewClipState(null);
      });
    }
  }, [previewClip, isPreviewMode]);

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

  // Find current clip (if playhead is inside a clip)
  const currentClip = clips.find(
    (c) => localCurrentTime >= c.start_time && localCurrentTime <= c.end_time
  );

  // Calculate subtitle time relative to clip start
  const subtitleRelativeTime = useMemo(() => {
    // If previewing a clip, use previewClip's start time
    if (isPreviewMode && previewClipState) {
      return localCurrentTime - previewClipState.start_time;
    }
    // Otherwise use the provided activeClipStartTime
    return localCurrentTime - activeClipStartTime;
  }, [localCurrentTime, isPreviewMode, activeClipStartTime, previewClipState]);

  // Sort clips by order for display
  const sortedClips = [...clips].sort((a, b) => a.order - b.order);

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
        {isPreviewMode && previewClipState && (
          <div className="absolute top-3 left-3 right-3 flex items-center justify-between">
            <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-indigo-600/90 backdrop-blur-sm text-white text-sm font-medium rounded-lg shadow-lg">
              <Play className="w-4 h-4 fill-current" />
              Preview: {previewClipState.title || 'Clip'}
              <span className="text-indigo-200">
                ({formatTime(previewClipState.start_time)} - {formatTime(previewClipState.end_time)})
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
          <EditorVideoControls
            isPlaying={isPlaying}
            isMuted={isMuted}
            currentTime={localCurrentTime}
            duration={videoDuration}
            clips={clips}
            onTogglePlay={togglePlay}
            onToggleMute={toggleMute}
            onSeek={handleSeek}
            onSkip={skip}
            onFullscreen={() => videoRef.current?.requestFullscreen()}
          />
        )}
      </div>

      {/* Mini Timeline with Clips */}
      {sortedClips.length > 0 && (
        <ClipsTimeline
          clips={clips}
          duration={videoDuration}
          currentTime={localCurrentTime}
          activeClipId={activeClipId}
          currentClip={currentClip}
          onClipClick={onClipClick}
        />
      )}
    </div>
  );
}
