'use client';

import React from 'react';
import {
  Play,
  Layers,
  Mic,
  ChevronDown,
  ChevronRight,
  Share2,
} from 'lucide-react';
import { formatTime } from '@/lib/utils';
import { DynamicKnowledgeGraphViewer } from '@/lib/dynamic';

interface Scene {
  scene_id: number;
  start_time: number;
  end_time: number;
  duration?: number;
  title?: string;
  summary?: string;
}

interface Chapter {
  chapter_id: number;
  title: string;
  start_time: number;
  end_time: number;
  scene_ids?: number[];
}

interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  text: string;
}

export type TabType = 'chapters' | 'transcript' | 'graph';

interface VideoPanelTabsProps {
  videoId?: string;
  scenes: Scene[];
  chapters: Chapter[];
  transcript: TranscriptSegment[];
  activeTab: TabType;
  expandedChapter: number | null;
  currentScene?: Scene;
  localCurrentTime: number;
  onTabChange: (tab: TabType) => void;
  onExpandChapter: (chapterId: number | null) => void;
  onSeek: (time: number) => void;
}

export function VideoPanelTabs({
  videoId,
  scenes,
  chapters,
  transcript,
  activeTab,
  expandedChapter,
  currentScene,
  localCurrentTime,
  onTabChange,
  onExpandChapter,
  onSeek,
}: VideoPanelTabsProps) {
  return (
    <>
      {/* Tab Buttons */}
      <div className="flex overflow-x-auto border-b border-[var(--sage-3)] scrollbar-none">
        <button
          onClick={() => onTabChange('chapters')}
          className={`flex-1 flex items-center justify-center gap-2 px-3 md:px-4 py-2.5 md:py-3 text-sm font-medium transition-colors whitespace-nowrap ${
            activeTab === 'chapters'
              ? 'text-amber-10 border-b-2 border-amber-9'
              : 'text-[var(--sage-8)] hover:text-[var(--sage-11)]'
          }`}
        >
          <Layers className="w-4 h-4" />
          Chapters
        </button>
        <button
          onClick={() => onTabChange('transcript')}
          className={`flex-1 flex items-center justify-center gap-2 px-3 md:px-4 py-2.5 md:py-3 text-sm font-medium transition-colors whitespace-nowrap ${
            activeTab === 'transcript'
              ? 'text-amber-10 border-b-2 border-amber-9'
              : 'text-[var(--sage-8)] hover:text-[var(--sage-11)]'
          }`}
        >
          <Mic className="w-4 h-4" />
          Transcript
        </button>
        {videoId && (
          <button
            onClick={() => onTabChange('graph')}
            className={`flex-1 flex items-center justify-center gap-2 px-3 md:px-4 py-2.5 md:py-3 text-sm font-medium transition-colors whitespace-nowrap ${
              activeTab === 'graph'
                ? 'text-amber-10 border-b-2 border-amber-9'
                : 'text-[var(--sage-8)] hover:text-[var(--sage-11)]'
            }`}
          >
            <Share2 className="w-4 h-4" />
            Graph
          </button>
        )}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'chapters' && (
          <ChaptersContent
            scenes={scenes}
            chapters={chapters}
            currentScene={currentScene}
            expandedChapter={expandedChapter}
            onExpandChapter={onExpandChapter}
            onSeek={onSeek}
          />
        )}

        {activeTab === 'transcript' && (
          <TranscriptContent
            transcript={transcript}
            localCurrentTime={localCurrentTime}
            onSeek={onSeek}
          />
        )}

        {activeTab === 'graph' && videoId && (
          <div className="h-full min-h-[400px]">
            <DynamicKnowledgeGraphViewer
              videoId={videoId}
              onSeek={onSeek}
              className="h-full"
            />
          </div>
        )}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Chapters tab                                                       */
/* ------------------------------------------------------------------ */

function ChaptersContent({
  scenes,
  chapters,
  currentScene,
  expandedChapter,
  onExpandChapter,
  onSeek,
}: {
  scenes: Scene[];
  chapters: Chapter[];
  currentScene?: Scene;
  expandedChapter: number | null;
  onExpandChapter: (id: number | null) => void;
  onSeek: (time: number) => void;
}) {
  if (chapters.length === 0 && scenes.length === 0) {
    return (
      <div className="p-3">
        <div className="text-center py-8">
          <Layers className="w-8 h-8 text-[var(--sage-6)] mx-auto mb-2" />
          <p className="text-sm text-[var(--sage-8)]">No chapters available</p>
        </div>
      </div>
    );
  }

  if (chapters.length === 0) {
    return (
      <div className="p-3 space-y-2">
        {scenes.map((scene) => {
          const isActive = currentScene?.scene_id === scene.scene_id;
          return (
            <button
              key={scene.scene_id}
              onClick={() => onSeek(scene.start_time)}
              className={`w-full text-left p-3 rounded-xl transition-all flex items-center gap-3 ${
                isActive ? 'bg-amber-2 border-l-4 border-amber-9' : 'hover:bg-[var(--sage-2)]'
              }`}
            >
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                  isActive ? 'bg-amber-9 text-white' : 'bg-[var(--sage-3)] text-[var(--sage-8)]'
                }`}
              >
                <Play className="w-3 h-3 fill-current" />
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm truncate ${isActive ? 'font-semibold text-amber-11' : 'text-[var(--sage-11)]'}`}>
                  {scene.title || `Scene ${scene.scene_id + 1}`}
                </p>
                <p className="text-xs text-[var(--sage-7)]">{formatTime(scene.start_time)}</p>
              </div>
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="p-3 space-y-2">
      {chapters.map((chapter) => {
        const isExpanded = expandedChapter === chapter.chapter_id;
        const chapterScenes = scenes.filter((s) => chapter.scene_ids?.includes(s.scene_id));
        const isActive = chapterScenes.some((s) => currentScene?.scene_id === s.scene_id);

        return (
          <div key={chapter.chapter_id} className="rounded-xl overflow-hidden bg-[var(--sage-2)]">
            <button
              onClick={() => onExpandChapter(isExpanded ? null : chapter.chapter_id)}
              className={`w-full text-left p-3 flex items-center gap-3 transition-all ${
                isActive ? 'bg-amber-2' : 'hover:bg-[var(--sage-3)]'
              }`}
            >
              {isExpanded ? (
                <ChevronDown className="w-4 h-4 text-[var(--sage-7)]" />
              ) : (
                <ChevronRight className="w-4 h-4 text-[var(--sage-7)]" />
              )}
              <div className="flex-1 min-w-0">
                <p className={`text-sm font-medium ${isActive ? 'text-amber-11' : 'text-[var(--sage-11)]'}`}>
                  {chapter.title}
                </p>
                <p className="text-xs text-[var(--sage-7)]">
                  {formatTime(chapter.start_time)} • {chapterScenes.length} scenes
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onSeek(chapter.start_time);
                }}
                className="p-1.5 hover:bg-amber-2 rounded-lg text-amber-9"
              >
                <Play className="w-3 h-3 fill-current" />
              </button>
            </button>

            {isExpanded && chapterScenes.length > 0 && (
              <div className="px-3 pb-3 space-y-1">
                {chapterScenes.map((scene) => {
                  const isSceneActive = currentScene?.scene_id === scene.scene_id;
                  return (
                    <button
                      key={scene.scene_id}
                      onClick={() => onSeek(scene.start_time)}
                      className={`w-full text-left pl-8 pr-3 py-2 rounded-lg transition-all text-sm ${
                        isSceneActive
                          ? 'bg-amber-2 text-amber-11 font-medium'
                          : 'text-[var(--sage-9)] hover:bg-white'
                      }`}
                    >
                      <span className="text-[var(--sage-7)] mr-2">{formatTime(scene.start_time)}</span>
                      {scene.title || `Scene ${scene.scene_id + 1}`}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Transcript tab                                                     */
/* ------------------------------------------------------------------ */

function TranscriptContent({
  transcript,
  localCurrentTime,
  onSeek,
}: {
  transcript: TranscriptSegment[];
  localCurrentTime: number;
  onSeek: (time: number) => void;
}) {
  if (transcript.length === 0) {
    return (
      <div className="p-3">
        <div className="text-center py-8">
          <Mic className="w-8 h-8 text-[var(--sage-6)] mx-auto mb-2" />
          <p className="text-sm text-[var(--sage-8)]">No transcript available</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-2">
      {transcript.map((segment) => {
        const isActive = localCurrentTime >= segment.start && localCurrentTime < segment.end;
        return (
          <button
            key={segment.id}
            onClick={() => onSeek(segment.start)}
            className={`w-full text-left p-3 rounded-xl transition-all ${
              isActive ? 'bg-amber-2 border-l-4 border-amber-9' : 'hover:bg-[var(--sage-2)]'
            }`}
          >
            <span className="text-xs text-amber-9 font-medium">
              {formatTime(segment.start)}
            </span>
            <p className={`text-sm mt-1 ${isActive ? 'text-amber-11 font-medium' : 'text-[var(--sage-11)]'}`}>
              {segment.text}
            </p>
          </button>
        );
      })}
    </div>
  );
}
