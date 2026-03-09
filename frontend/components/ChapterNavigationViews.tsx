'use client';

import React from 'react';
import {
  ChevronRight,
  Play,
  Film,
  Sparkles,
  Tag,
  Layers,
} from 'lucide-react';
import { formatTime } from '@/lib/utils';

interface Scene {
  scene_id: number;
  start_time: number;
  end_time: number;
  duration: number;
  title?: string;
  summary?: string;
  detected_objects?: string[];
  transcript_segment?: string;
}

interface Chapter {
  chapter_id: number;
  title: string;
  start_time: number;
  end_time: number;
  duration: number;
  scene_ids: number[];
  themes?: string[];
  summary?: string;
}

interface VideoStructure {
  scenes: Scene[];
  chapters: Chapter[];
  video_summary?: string;
  video_title?: string;
  key_topics?: string[];
}

/* ------------------------------------------------------------------ */
/*  Summary View                                                       */
/* ------------------------------------------------------------------ */

interface SummaryViewProps {
  structure: VideoStructure;
  scenesCount: number;
  chaptersCount: number;
}

export function SummaryView({ structure, scenesCount, chaptersCount }: SummaryViewProps) {
  return (
    <div className="p-5 space-y-4">
      {structure.video_title && (
        <div>
          <h4 className="text-lg font-bold text-gray-900 mb-2">
            {structure.video_title}
          </h4>
        </div>
      )}

      {structure.video_summary && (
        <div className="bg-indigo-50 rounded-xl p-4">
          <div className="flex items-center gap-2 text-indigo-700 text-xs font-semibold mb-2">
            <Sparkles className="w-3 h-3" />
            AI Summary
          </div>
          <p className="text-gray-700 text-sm leading-relaxed">
            {structure.video_summary}
          </p>
        </div>
      )}

      {structure.key_topics && structure.key_topics.length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-gray-500 text-xs font-semibold mb-2">
            <Tag className="w-3 h-3" />
            Key Topics
          </div>
          <div className="flex flex-wrap gap-2">
            {structure.key_topics.map((topic, i) => (
              <span
                key={i}
                className="px-3 py-1 bg-gray-100 text-gray-700 rounded-full text-xs font-medium"
              >
                {topic}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 pt-2">
        <div className="bg-gray-50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-gray-900">{chaptersCount}</div>
          <div className="text-xs text-gray-500">Chapters</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-gray-900">{scenesCount}</div>
          <div className="text-xs text-gray-500">Scenes</div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Chapters List                                                      */
/* ------------------------------------------------------------------ */

interface ChaptersListProps {
  chapters: Chapter[];
  scenes: Scene[];
  expandedChapters: Set<number>;
  currentScene?: Scene;
  currentChapter?: Chapter | null;
  onToggleChapter: (chapterId: number) => void;
  onSeek: (time: number) => void;
  getProgressPercent: (start: number, end: number) => number;
}

export function ChaptersList({
  chapters,
  scenes,
  expandedChapters,
  currentScene,
  currentChapter,
  onToggleChapter,
  onSeek,
  getProgressPercent,
}: ChaptersListProps) {
  return (
    <div className="p-3 space-y-2">
      {chapters.map((chapter) => {
        const isExpanded = expandedChapters.has(chapter.chapter_id);
        const isCurrent = currentChapter?.chapter_id === chapter.chapter_id;
        const chapterScenes = scenes.filter(
          s => chapter.scene_ids?.includes(s.scene_id)
        );

        return (
          <div key={chapter.chapter_id} className="rounded-xl overflow-hidden">
            <button
              onClick={() => onToggleChapter(chapter.chapter_id)}
              className={`w-full text-left p-4 transition-all flex items-start gap-3 ${
                isCurrent
                  ? 'bg-indigo-50 border-l-4 border-indigo-500'
                  : 'bg-gray-50 hover:bg-gray-100'
              }`}
            >
              <div className={`mt-0.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                <ChevronRight className="w-4 h-4 text-gray-400" />
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <h4 className={`font-semibold truncate ${
                    isCurrent ? 'text-indigo-700' : 'text-gray-900'
                  }`}>
                    {chapter.title}
                  </h4>
                  <span className="text-xs text-gray-400 ml-2 flex-shrink-0">
                    {formatTime(chapter.start_time)}
                  </span>
                </div>

                {chapter.summary && (
                  <p className="text-xs text-gray-500 line-clamp-2">
                    {chapter.summary}
                  </p>
                )}

                <div className="mt-2 h-1 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 transition-all duration-300"
                    style={{ width: `${getProgressPercent(chapter.start_time, chapter.end_time)}%` }}
                  />
                </div>
              </div>
            </button>

            {isExpanded && (
              <div className="bg-white border-t border-gray-100">
                {chapterScenes.map((scene) => {
                  const isCurrentScene = currentScene?.scene_id === scene.scene_id;

                  return (
                    <button
                      key={scene.scene_id}
                      onClick={() => onSeek(scene.start_time)}
                      className={`w-full text-left p-3 pl-10 border-b border-gray-50 last:border-b-0 transition-all flex items-center gap-3 group ${
                        isCurrentScene ? 'bg-indigo-50' : 'hover:bg-gray-50'
                      }`}
                    >
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${
                        isCurrentScene
                          ? 'bg-indigo-500 text-white'
                          : 'bg-gray-200 text-gray-500 group-hover:bg-indigo-100 group-hover:text-indigo-600'
                      }`}>
                        <Play className="w-3 h-3 fill-current" />
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className={`text-sm truncate ${
                            isCurrentScene ? 'font-medium text-indigo-700' : 'text-gray-700'
                          }`}>
                            {scene.title || `Scene ${scene.scene_id + 1}`}
                          </span>
                          <span className="text-xs text-gray-400 ml-2">
                            {formatTime(scene.start_time)}
                          </span>
                        </div>

                        {scene.detected_objects && scene.detected_objects.length > 0 && (
                          <div className="flex gap-1 mt-1 overflow-hidden">
                            {scene.detected_objects.slice(0, 3).map((obj, i) => (
                              <span key={i} className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                                {obj}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
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
/*  Scenes List                                                        */
/* ------------------------------------------------------------------ */

interface ScenesListProps {
  scenes: Scene[];
  currentScene?: Scene;
  onSeek: (time: number) => void;
  getProgressPercent: (start: number, end: number) => number;
}

export function ScenesList({
  scenes,
  currentScene,
  onSeek,
  getProgressPercent,
}: ScenesListProps) {
  return (
    <div className="p-3 space-y-1">
      {scenes.map((scene) => {
        const isCurrentScene = currentScene?.scene_id === scene.scene_id;

        return (
          <button
            key={scene.scene_id}
            onClick={() => onSeek(scene.start_time)}
            className={`w-full text-left p-3 rounded-xl transition-all flex items-start gap-3 group ${
              isCurrentScene
                ? 'bg-indigo-50 border border-indigo-200'
                : 'hover:bg-gray-50 border border-transparent'
            }`}
          >
            <div className={`w-16 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
              isCurrentScene
                ? 'bg-indigo-200'
                : 'bg-gray-200 group-hover:bg-indigo-100'
            }`}>
              <Film className={`w-5 h-5 ${
                isCurrentScene ? 'text-indigo-600' : 'text-gray-400'
              }`} />
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between mb-1">
                <span className={`text-sm font-medium truncate ${
                  isCurrentScene ? 'text-indigo-700' : 'text-gray-900'
                }`}>
                  {scene.title || `Scene ${scene.scene_id + 1}`}
                </span>
                <span className="text-xs text-gray-400 ml-2 flex-shrink-0">
                  {formatTime(scene.start_time)}
                </span>
              </div>

              {scene.summary && (
                <p className="text-xs text-gray-500 line-clamp-2">
                  {scene.summary}
                </p>
              )}

              <div className="mt-2 flex items-center gap-2">
                <div className="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 transition-all duration-300"
                    style={{ width: `${getProgressPercent(scene.start_time, scene.end_time)}%` }}
                  />
                </div>
                <span className="text-[10px] text-gray-400">
                  {Math.round(scene.duration)}s
                </span>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
