'use client';

import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import WaveSurfer from 'wavesurfer.js';
import { ZoomIn, ZoomOut, Loader2 } from 'lucide-react';
import { Clip } from '@/lib/api';
import { formatTime } from '@/lib/utils';

interface TimelineWaveformProps {
  /** URL of the video/audio to display waveform */
  videoUrl?: string;
  /** Total duration in seconds */
  duration: number;
  /** Clips to overlay on timeline */
  clips: Clip[];
  /** Current playhead position */
  currentTime: number;
  /** Called when user seeks on timeline */
  onSeek?: (time: number) => void;
  /** Called when clip is clicked */
  onClipClick?: (clip: Clip) => void;
  /** Called when clip boundaries are modified via drag */
  onClipModify?: (clipId: string, startTime: number, endTime: number) => void;
  /** Currently active/selected clip */
  activeClipId?: string;
  /** Minimum zoom level */
  minZoom?: number;
  /** Maximum zoom level */
  maxZoom?: number;
}

/**
 * Timeline component with audio waveform visualization and draggable clip overlays.
 * Uses wavesurfer.js for waveform rendering.
 */
export default function TimelineWaveform({
  videoUrl,
  duration,
  clips,
  currentTime,
  onSeek,
  onClipClick,
  onClipModify,
  activeClipId,
  minZoom = 1,
  maxZoom = 200,
}: TimelineWaveformProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wavesurferRef = useRef<WaveSurfer | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const [zoom, setZoom] = useState(minZoom);
  const [dragState, setDragState] = useState<{
    clipId: string;
    edge: 'start' | 'end';
    initialX: number;
    initialTime: number;
  } | null>(null);

  // Color palette for clips
  const clipColors = useMemo(() => [
    { bg: 'rgba(99, 102, 241, 0.4)', border: 'rgb(99, 102, 241)' },   // indigo
    { bg: 'rgba(168, 85, 247, 0.4)', border: 'rgb(168, 85, 247)' },   // purple
    { bg: 'rgba(59, 130, 246, 0.4)', border: 'rgb(59, 130, 246)' },   // blue
    { bg: 'rgba(6, 182, 212, 0.4)', border: 'rgb(6, 182, 212)' },     // cyan
    { bg: 'rgba(20, 184, 166, 0.4)', border: 'rgb(20, 184, 166)' },   // teal
    { bg: 'rgba(34, 197, 94, 0.4)', border: 'rgb(34, 197, 94)' },     // green
    { bg: 'rgba(245, 158, 11, 0.4)', border: 'rgb(245, 158, 11)' },   // amber
    { bg: 'rgba(249, 115, 22, 0.4)', border: 'rgb(249, 115, 22)' },   // orange
  ], []);

  // Initialize WaveSurfer
  useEffect(() => {
    if (!containerRef.current || !videoUrl) return;

    Promise.resolve().then(() => {
      setIsLoading(true);
      setIsReady(false);
    });

    const wavesurfer = WaveSurfer.create({
      container: containerRef.current,
      waveColor: '#cbd5e1',      // slate-300
      progressColor: '#6366f1',  // indigo-500
      cursorColor: '#ef4444',    // red-500
      cursorWidth: 2,
      height: 80,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: true,
      interact: true,
      hideScrollbar: false,
      minPxPerSec: zoom,
    });

    wavesurfer.on('ready', () => {
      setIsLoading(false);
      setIsReady(true);
    });

    wavesurfer.on('error', (err) => {
      console.error('WaveSurfer error:', err);
      setIsLoading(false);
    });

    wavesurfer.on('click', (relativeX) => {
      const time = relativeX * duration;
      onSeek?.(time);
    });

    // Load audio from video URL
    wavesurfer.load(videoUrl);
    wavesurferRef.current = wavesurfer;

    return () => {
      wavesurfer.destroy();
      wavesurferRef.current = null;
    };
  }, [videoUrl, duration, onSeek, zoom]);

  // Update zoom level
  useEffect(() => {
    if (wavesurferRef.current && isReady) {
      wavesurferRef.current.zoom(zoom);
    }
  }, [zoom, isReady]);

  // Sync playhead position
  useEffect(() => {
    if (wavesurferRef.current && isReady && duration > 0) {
      const progress = currentTime / duration;
      wavesurferRef.current.seekTo(Math.min(1, Math.max(0, progress)));
    }
  }, [currentTime, duration, isReady]);

  // Handle zoom in/out
  const handleZoomIn = useCallback(() => {
    setZoom((prev) => Math.min(maxZoom, prev * 1.5));
  }, [maxZoom]);

  const handleZoomOut = useCallback(() => {
    setZoom((prev) => Math.max(minZoom, prev / 1.5));
  }, [minZoom]);

  // Handle drag start on clip edge
  const handleDragStart = useCallback((
    e: React.MouseEvent,
    clipId: string,
    edge: 'start' | 'end',
    initialTime: number
  ) => {
    e.stopPropagation();
    e.preventDefault();
    setDragState({
      clipId,
      edge,
      initialX: e.clientX,
      initialTime,
    });
  }, []);

  // Handle drag move
  useEffect(() => {
    if (!dragState) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;

      const rect = containerRef.current.getBoundingClientRect();
      const containerWidth = rect.width;
      const pixelsPerSecond = containerWidth / duration * zoom;
      const deltaX = e.clientX - dragState.initialX;
      const deltaTime = deltaX / pixelsPerSecond;

      const clip = clips.find((c) => c.id === dragState.clipId);
      if (!clip) return;

      if (dragState.edge === 'start') {
        Math.max(0, Math.min(clip.end_time - 1, dragState.initialTime + deltaTime));
      } else {
        Math.min(duration, Math.max(clip.start_time + 1, dragState.initialTime + deltaTime));
      }

      // Visual feedback only during drag - actual update on mouseup
      // Could add visual preview here
    };

    const handleMouseUp = (e: MouseEvent) => {
      if (!containerRef.current || !dragState) return;

      const rect = containerRef.current.getBoundingClientRect();
      const containerWidth = rect.width;
      const pixelsPerSecond = containerWidth / duration * zoom;
      const deltaX = e.clientX - dragState.initialX;
      const deltaTime = deltaX / pixelsPerSecond;

      const clip = clips.find((c) => c.id === dragState.clipId);
      if (!clip) {
        setDragState(null);
        return;
      }

      let newStartTime = clip.start_time;
      let newEndTime = clip.end_time;

      if (dragState.edge === 'start') {
        newStartTime = Math.max(0, Math.min(clip.end_time - 1, dragState.initialTime + deltaTime));
      } else {
        newEndTime = Math.min(duration, Math.max(clip.start_time + 1, dragState.initialTime + deltaTime));
      }

      // Only call modify if there's actual change
      if (newStartTime !== clip.start_time || newEndTime !== clip.end_time) {
        onClipModify?.(dragState.clipId, newStartTime, newEndTime);
      }

      setDragState(null);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [dragState, clips, duration, zoom, onClipModify]);

  // Sort clips by start time for rendering
  const sortedClips = useMemo(() => 
    [...clips].sort((a, b) => a.start_time - b.start_time),
    [clips]
  );

  return (
    <div className="flex flex-col border-t border-gray-200 bg-slate-50">
      {/* Header with zoom controls */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-500 uppercase">
            Timeline
          </span>
          {isLoading && (
            <Loader2 className="w-4 h-4 text-indigo-500 animate-spin" />
          )}
        </div>
        
        <div className="flex items-center gap-1">
          <button
            onClick={handleZoomOut}
            disabled={zoom <= minZoom}
            className="p-1.5 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title="Zoom out"
          >
            <ZoomOut className="w-4 h-4 text-gray-600" />
          </button>
          <span className="text-xs text-gray-500 min-w-[3rem] text-center">
            {Math.round(zoom)}x
          </span>
          <button
            onClick={handleZoomIn}
            disabled={zoom >= maxZoom}
            className="p-1.5 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title="Zoom in"
          >
            <ZoomIn className="w-4 h-4 text-gray-600" />
          </button>
        </div>
      </div>

      {/* Waveform container with clips overlay */}
      <div className="relative">
        {/* WaveSurfer container */}
        <div 
          ref={containerRef}
          className="w-full overflow-x-auto"
          style={{ minHeight: 80 }}
        />

        {/* Clips overlay */}
        {isReady && duration > 0 && (
          <div className="absolute inset-0 pointer-events-none overflow-x-auto">
            <div 
              className="relative h-full"
              style={{ 
                width: `${Math.max(100, duration * zoom)}px`,
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

                    {/* Drag handles */}
                    {/* Left handle (start time) */}
                    <div
                      className={`absolute left-0 top-0 bottom-0 w-2 cursor-ew-resize group ${
                        dragState?.clipId === clip.id && dragState?.edge === 'start' 
                          ? 'bg-white/50' 
                          : 'hover:bg-white/30'
                      }`}
                      onMouseDown={(e) => handleDragStart(e, clip.id, 'start', clip.start_time)}
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
                      onMouseDown={(e) => handleDragStart(e, clip.id, 'end', clip.end_time)}
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
          </div>
        )}

        {/* Loading overlay */}
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-100/80">
            <div className="flex items-center gap-2 text-gray-500">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="text-sm">Loading waveform...</span>
            </div>
          </div>
        )}

        {/* No video message */}
        {!videoUrl && (
          <div className="flex items-center justify-center h-20 text-gray-400 text-sm">
            No video loaded
          </div>
        )}
      </div>

      {/* Time markers */}
      {isReady && duration > 0 && (
        <div className="flex justify-between px-4 py-1 text-xs text-gray-400 border-t border-gray-200">
          <span>{formatTime(0)}</span>
          <span>{formatTime(duration / 4)}</span>
          <span>{formatTime(duration / 2)}</span>
          <span>{formatTime((duration / 4) * 3)}</span>
          <span>{formatTime(duration)}</span>
        </div>
      )}
    </div>
  );
}
