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
      <div className="flex border-b border-gray-100">
        <button
          onClick={() => onTabChange('chapters')}
          className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors ${
            activeTab === 'chapters'
              ? 'text-indigo-600 border-b-2 border-indigo-600'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          <Layers className="w-4 h-4" />
          Chapters
        </button>
        <button
          onClick={() => onTabChange('transcript')}
          className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors ${
            activeTab === 'transcript'
              ? 'text-indigo-600 border-b-2 border-indigo-600'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          <Mic className="w-4 h-4" />
          Transcript
        </button>
        {videoId && (
          <button
            onClick={() => onTabChange('graph')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === 'graph'
                ? 'text-indigo-600 border-b-2 border-indigo-600'
                : 'text-gray-500 hover:text-gray-700'
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
          <Layers className="w-8 h-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No chapters available</p>
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
                isActive ? 'bg-indigo-50 border-l-4 border-indigo-500' : 'hover:bg-gray-50'
              }`}
            >
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                  isActive ? 'bg-indigo-500 text-white' : 'bg-gray-100 text-gray-500'
                }`}
              >
                <Play className="w-3 h-3 fill-current" />
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm truncate ${isActive ? 'font-semibold text-indigo-700' : 'text-gray-700'}`}>
                  {scene.title || `Scene ${scene.scene_id + 1}`}
                </p>
                <p className="text-xs text-gray-400">{formatTime(scene.start_time)}</p>
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
          <div key={chapter.chapter_id} className="rounded-xl overflow-hidden bg-gray-50">
            <button
              onClick={() => onExpandChapter(isExpanded ? null : chapter.chapter_id)}
              className={`w-full text-left p-3 flex items-center gap-3 transition-all ${
                isActive ? 'bg-indigo-50' : 'hover:bg-gray-100'
              }`}
            >
              {isExpanded ? (
                <ChevronDown className="w-4 h-4 text-gray-400" />
              ) : (
                <ChevronRight className="w-4 h-4 text-gray-400" />
              )}
              <div className="flex-1 min-w-0">
                <p className={`text-sm font-medium ${isActive ? 'text-indigo-700' : 'text-gray-700'}`}>
                  {chapter.title}
                </p>
                <p className="text-xs text-gray-400">
                  {formatTime(chapter.start_time)} • {chapterScenes.length} scenes
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onSeek(chapter.start_time);
                }}
                className="p-1.5 hover:bg-indigo-100 rounded-lg text-indigo-500"
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
                          ? 'bg-indigo-100 text-indigo-700 font-medium'
                          : 'text-gray-600 hover:bg-white'
                      }`}
                    >
                      <span className="text-gray-400 mr-2">{formatTime(scene.start_time)}</span>
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
          <Mic className="w-8 h-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No transcript available</p>
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
              isActive ? 'bg-indigo-50 border-l-4 border-indigo-500' : 'hover:bg-gray-50'
            }`}
          >
            <span className="text-xs text-indigo-500 font-medium">
              {formatTime(segment.start)}
            </span>
            <p className={`text-sm mt-1 ${isActive ? 'text-indigo-700 font-medium' : 'text-gray-700'}`}>
              {segment.text}
            </p>
          </button>
        );
      })}
    </div>
  );
}
