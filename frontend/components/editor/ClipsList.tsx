'use client';

import React, { useState, useCallback } from 'react';
import { Plus, Sparkles, Film, GripVertical, Download } from 'lucide-react';
import { Clip } from '@/lib/api';
import ClipCard from './ClipCard';

interface ClipsListProps {
  clips: Clip[];
  activeClipId?: string;
  onClipClick?: (clip: Clip) => void;
  onClipPlay?: (clip: Clip) => void;
  onClipDelete?: (clip: Clip) => void;
  onClipSubtitlesToggle?: (clip: Clip) => void;
  onClipExport?: (clip: Clip) => void;
  onExportAll?: () => void;
  onGenerateAutoClips?: () => void;
  onClipsReorder?: (clipOrders: { clip_id: string; order: number }[]) => void;
  isLoading?: boolean;
}

/**
 * List of clips in the project with drag & drop reordering
 */
export default function ClipsList({
  clips,
  activeClipId,
  onClipClick,
  onClipPlay,
  onClipDelete,
  onClipSubtitlesToggle,
  onClipExport,
  onExportAll,
  onGenerateAutoClips,
  onClipsReorder,
  isLoading = false,
}: ClipsListProps) {
  const [draggedClipId, setDraggedClipId] = useState<string | null>(null);
  const [dragOverClipId, setDragOverClipId] = useState<string | null>(null);

  // Sort clips by order
  const sortedClips = [...clips].sort((a, b) => a.order - b.order);

  // Calculate total duration
  const totalDuration = clips.reduce((sum, clip) => sum + (clip.end_time - clip.start_time), 0);

  const formatTime = (seconds: number): string => {
    if (!seconds || isNaN(seconds)) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Drag & Drop handlers
  const handleDragStart = useCallback((e: React.DragEvent, clipId: string) => {
    setDraggedClipId(clipId);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', clipId);
    // Add a slight delay to show the drag feedback
    setTimeout(() => {
      const element = e.currentTarget as HTMLElement;
      element.style.opacity = '0.5';
    }, 0);
  }, []);

  const handleDragEnd = useCallback((e: React.DragEvent) => {
    setDraggedClipId(null);
    setDragOverClipId(null);
    const element = e.currentTarget as HTMLElement;
    element.style.opacity = '1';
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, clipId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (clipId !== draggedClipId) {
      setDragOverClipId(clipId);
    }
  }, [draggedClipId]);

  const handleDragLeave = useCallback(() => {
    setDragOverClipId(null);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent, targetClipId: string) => {
    e.preventDefault();
    const sourceClipId = e.dataTransfer.getData('text/plain');
    
    if (sourceClipId && sourceClipId !== targetClipId && onClipsReorder) {
      // Find indices
      const sourceIndex = sortedClips.findIndex(c => c.id === sourceClipId);
      const targetIndex = sortedClips.findIndex(c => c.id === targetClipId);
      
      if (sourceIndex !== -1 && targetIndex !== -1) {
        // Create new order
        const newClips = [...sortedClips];
        const [removed] = newClips.splice(sourceIndex, 1);
        newClips.splice(targetIndex, 0, removed);
        
        // Generate new orders
        const newOrders = newClips.map((clip, index) => ({
          clip_id: clip.id,
          order: index,
        }));
        
        onClipsReorder(newOrders);
      }
    }
    
    setDraggedClipId(null);
    setDragOverClipId(null);
  }, [sortedClips, onClipsReorder]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <div>
          <h3 className="font-semibold text-gray-900 text-sm">
            Clips ({clips.length})
          </h3>
          {clips.length > 0 && (
            <p className="text-xs text-gray-500">
              Total: {formatTime(totalDuration)}
              {onClipsReorder && <span className="ml-2 text-gray-400">• Drag to reorder</span>}
            </p>
          )}
        </div>

        {onGenerateAutoClips && (
          <button
            onClick={onGenerateAutoClips}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-purple-500 to-indigo-600 text-white text-sm font-medium rounded-lg hover:from-purple-600 hover:to-indigo-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Sparkles className="w-4 h-4" />
            Auto-Clips
          </button>
        )}
      </div>

      {/* Clips List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {isLoading ? (
          // Loading state
          <div className="flex flex-col items-center justify-center py-12 text-gray-400">
            <div className="w-8 h-8 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mb-3" />
            <p className="text-sm">Generating clips...</p>
          </div>
        ) : clips.length === 0 ? (
          // Empty state
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
              <Film className="w-8 h-8 text-gray-400" />
            </div>
            <h4 className="font-medium text-gray-900 mb-1">No clips yet</h4>
            <p className="text-sm text-gray-500 mb-4 max-w-[200px]">
              Use the chat to search and create clips, or generate them automatically.
            </p>
            {onGenerateAutoClips && (
              <button
                onClick={onGenerateAutoClips}
                className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-500 to-indigo-600 text-white text-sm font-medium rounded-lg hover:from-purple-600 hover:to-indigo-700 transition-all"
              >
                <Sparkles className="w-4 h-4" />
                Generate Auto-Clips
              </button>
            )}
          </div>
        ) : (
          // Clips list with drag & drop
          sortedClips.map((clip, index) => (
            <div
              key={clip.id}
              draggable={!!onClipsReorder}
              onDragStart={(e) => handleDragStart(e, clip.id)}
              onDragEnd={handleDragEnd}
              onDragOver={(e) => handleDragOver(e, clip.id)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, clip.id)}
              className={`relative transition-all ${
                dragOverClipId === clip.id && draggedClipId !== clip.id
                  ? 'transform translate-y-1'
                  : ''
              }`}
            >
              {/* Drop indicator */}
              {dragOverClipId === clip.id && draggedClipId !== clip.id && (
                <div className="absolute -top-1.5 left-0 right-0 h-0.5 bg-indigo-500 rounded-full z-10" />
              )}
              
              {/* Clip card with drag handle */}
              <div className={`flex items-stretch ${onClipsReorder ? 'group' : ''}`}>
                {onClipsReorder && (
                  <div 
                    className="flex items-center justify-center w-6 cursor-grab active:cursor-grabbing text-gray-300 hover:text-gray-500 transition-colors"
                  >
                    <GripVertical className="w-4 h-4" />
                  </div>
                )}
                <div className="flex-1">
                  <ClipCard
                    clip={clip}
                    index={index}
                    isActive={clip.id === activeClipId}
                    isDragging={draggedClipId === clip.id}
                    onClick={() => onClipClick?.(clip)}
                    onPlay={() => onClipPlay?.(clip)}
                    onDelete={() => onClipDelete?.(clip)}
                    onSubtitlesToggle={() => onClipSubtitlesToggle?.(clip)}
                    onExport={() => onClipExport?.(clip)}
                  />
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Footer with stats and export button */}
      {clips.length > 0 && (
        <div className="px-4 py-3 border-t border-gray-100 bg-gray-50">
          <div className="flex items-center justify-between">
            <div className="text-xs text-gray-500">
              <span>{clips.filter((c) => c.subtitles_enabled).length} with subtitles</span>
              <span className="mx-2">•</span>
              <span>{clips.filter((c) => c.export_status === 'done').length} exported</span>
            </div>
            {onExportAll && clips.length > 0 && (
              <button
                onClick={onExportAll}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white text-xs font-medium rounded-lg hover:bg-indigo-700 transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                Export All
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
