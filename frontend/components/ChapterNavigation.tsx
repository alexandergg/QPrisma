'use client';

import React, { useState, useMemo } from 'react';
import {
  Clock,
  Layers,
  BookOpen,
} from 'lucide-react';
import { formatTime } from '@/lib/utils';
import { SummaryView, ChaptersList, ScenesList } from './ChapterNavigationViews';
import type { VideoStructure } from '@/types';

interface ChapterNavigationProps {
  structure: VideoStructure;
  currentTime: number;
  onSeek: (timestamp: number) => void;
  duration: number;
}

export default function ChapterNavigation({
  structure,
  currentTime,
  onSeek,
  duration
}: ChapterNavigationProps) {
  const [expandedChapters, setExpandedChapters] = useState<Set<number>>(new Set([0]));
  const [viewMode, setViewMode] = useState<'chapters' | 'scenes' | 'summary'>('chapters');

  const scenes = useMemo(() => structure?.scenes || [], [structure?.scenes]);
  const chapters = useMemo(() => structure?.chapters || [], [structure?.chapters]);

  const currentScene = useMemo(() => {
    return scenes.find(
      s => currentTime >= s.start_time && currentTime < s.end_time
    );
  }, [scenes, currentTime]);

  const currentChapter = useMemo(() => {
    if (!currentScene) return null;
    return chapters.find(
      c => c.scene_ids?.includes(currentScene.scene_id)
    );
  }, [chapters, currentScene]);

  if (!structure || (scenes.length === 0 && chapters.length === 0)) {
    return (
      <div className="bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 p-6 text-center">
        <Layers className="w-8 h-8 text-gray-300 mx-auto mb-3" />
        <p className="text-gray-500 text-sm">No chapter data available</p>
        <p className="text-gray-400 text-xs mt-1">Process video with optimized pipeline to generate chapters</p>
      </div>
    );
  }

  const toggleChapter = (chapterId: number) => {
    const newExpanded = new Set(expandedChapters);
    if (newExpanded.has(chapterId)) {
      newExpanded.delete(chapterId);
    } else {
      newExpanded.add(chapterId);
    }
    setExpandedChapters(newExpanded);
  };

  const getProgressPercent = (start: number, end: number) => {
    if (currentTime < start) return 0;
    if (currentTime >= end) return 100;
    return ((currentTime - start) / (end - start)) * 100;
  };

  return (
    <div className="bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 overflow-hidden flex flex-col h-full">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-100">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-bold text-gray-900 flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-indigo-500" />
            Navigation
          </h3>
          <div className="flex items-center gap-1 text-xs">
            <span className="text-gray-500">{scenes.length} scenes</span>
            <span className="text-gray-300">|</span>
            <span className="text-gray-500">{chapters.length} chapters</span>
          </div>
        </div>

        {/* View Mode Tabs */}
        <div className="flex items-center gap-1 bg-gray-100 p-1 rounded-lg">
          {(['chapters', 'scenes', 'summary'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={`flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-all capitalize ${
                viewMode === mode
                  ? 'bg-white text-indigo-600 shadow'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {viewMode === 'summary' && (
          <SummaryView
            structure={structure}
            scenesCount={scenes.length}
            chaptersCount={chapters.length}
          />
        )}

        {viewMode === 'chapters' && (
          <ChaptersList
            chapters={chapters}
            scenes={scenes}
            expandedChapters={expandedChapters}
            currentScene={currentScene}
            currentChapter={currentChapter}
            onToggleChapter={toggleChapter}
            onSeek={onSeek}
            getProgressPercent={getProgressPercent}
          />
        )}

        {viewMode === 'scenes' && (
          <ScenesList
            scenes={scenes}
            currentScene={currentScene}
            onSeek={onSeek}
            getProgressPercent={getProgressPercent}
          />
        )}
      </div>

      {/* Current Position Indicator */}
      <div className="px-5 py-3 border-t border-gray-100 bg-gray-50">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <Clock className="w-3 h-3 text-gray-400" />
            <span className="text-gray-600">{formatTime(currentTime)}</span>
            <span className="text-gray-300">/</span>
            <span className="text-gray-400">{formatTime(duration)}</span>
          </div>
          {currentScene && (
            <div className="flex items-center gap-2 text-indigo-600">
              <Layers className="w-3 h-3" />
              <span className="font-medium">{currentScene.title || `Scene ${currentScene.scene_id + 1}`}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
