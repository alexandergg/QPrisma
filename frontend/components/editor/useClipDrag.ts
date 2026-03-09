'use client';

import React, { useState, useCallback, useEffect, type RefObject } from 'react';
import { Clip } from '@/lib/api';

export interface DragState {
  clipId: string;
  edge: 'start' | 'end';
  initialX: number;
  initialTime: number;
}

/**
 * Hook for managing clip edge drag interactions on a timeline.
 *
 * Handles mouse-down on a drag handle, tracks mouse-move for visual
 * feedback, and commits the boundary change on mouse-up via `onClipModify`.
 */
export function useClipDrag(
  containerRef: RefObject<HTMLDivElement | null>,
  clips: Clip[],
  duration: number,
  zoom: number,
  onClipModify?: (clipId: string, startTime: number, endTime: number) => void,
) {
  const [dragState, setDragState] = useState<DragState | null>(null);

  const handleDragStart = useCallback(
    (
      e: React.MouseEvent,
      clipId: string,
      edge: 'start' | 'end',
      initialTime: number,
    ) => {
      e.stopPropagation();
      e.preventDefault();
      setDragState({ clipId, edge, initialX: e.clientX, initialTime });
    },
    [],
  );

  // Attach document-level listeners while dragging
  useEffect(() => {
    if (!dragState) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;

      const rect = containerRef.current.getBoundingClientRect();
      const pixelsPerSecond = (rect.width / duration) * zoom;
      const deltaX = e.clientX - dragState.initialX;
      const deltaTime = deltaX / pixelsPerSecond;

      const clip = clips.find((c) => c.id === dragState.clipId);
      if (!clip) return;

      // Visual feedback only during drag – actual update on mouseup
      if (dragState.edge === 'start') {
        Math.max(0, Math.min(clip.end_time - 1, dragState.initialTime + deltaTime));
      } else {
        Math.min(duration, Math.max(clip.start_time + 1, dragState.initialTime + deltaTime));
      }
    };

    const handleMouseUp = (e: MouseEvent) => {
      if (!containerRef.current || !dragState) return;

      const rect = containerRef.current.getBoundingClientRect();
      const pixelsPerSecond = (rect.width / duration) * zoom;
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
        newStartTime = Math.max(
          0,
          Math.min(clip.end_time - 1, dragState.initialTime + deltaTime),
        );
      } else {
        newEndTime = Math.min(
          duration,
          Math.max(clip.start_time + 1, dragState.initialTime + deltaTime),
        );
      }

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
  }, [dragState, clips, duration, zoom, onClipModify, containerRef]);

  return { dragState, handleDragStart };
}
