'use client';

import React, { useState, useMemo, useCallback } from 'react';
import useSWR from 'swr';
import {
  Play,
  Layers,
  Mic,
  ChevronDown,
  ChevronRight,
  Share2,
  BarChart3,
} from 'lucide-react';
import { formatTime } from '@/lib/utils';
import { apiClient } from '@/lib/api';
import { DynamicKnowledgeGraphViewer } from '@/lib/dynamic';
import { ChapterDetailModal } from '@/components/chapters/ChapterDetailModal';
import type { GraphVisualizationData, GraphNode } from '@/types';

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
  // Fetch graph data for chapter entity pills + modal graph
  const { data: graphData } = useSWR<GraphVisualizationData>(
    videoId && chapters.length > 0 ? `chapter-graph-${videoId}` : null,
    () => apiClient.getVideoVisualization(videoId!, { depth: 2 }),
    { revalidateOnFocus: false },
  );

  // Chapter detail modal state
  const [modalChapterId, setModalChapterId] = useState<number | null>(null);

  const modalChapter = useMemo(
    () => chapters.find((c) => c.chapter_id === modalChapterId) ?? null,
    [chapters, modalChapterId],
  );

  const handleOpenModal = useCallback((chapterId: number) => {
    setModalChapterId(chapterId);
  }, []);

  const handleNavigateModal = useCallback((chapterId: number) => {
    setModalChapterId(chapterId);
  }, []);

  return (
    <>
      {/* Tab Buttons */}
      <div className="flex border-b border-[var(--border-subtle)]">
        <button
          onClick={() => onTabChange('chapters')}
          className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors ${
            activeTab === 'chapters'
              ? 'text-indigo-600 border-b-2 border-indigo-600 dark:text-indigo-400 dark:border-indigo-400'
              : 'text-[var(--text-secondary)] hover:text-[var(--foreground)]'
          }`}
        >
          <Layers className="w-4 h-4" />
          Chapters
        </button>
        <button
          onClick={() => onTabChange('transcript')}
          className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors ${
            activeTab === 'transcript'
              ? 'text-indigo-600 border-b-2 border-indigo-600 dark:text-indigo-400 dark:border-indigo-400'
              : 'text-[var(--text-secondary)] hover:text-[var(--foreground)]'
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
                ? 'text-indigo-600 border-b-2 border-indigo-600 dark:text-indigo-400 dark:border-indigo-400'
                : 'text-[var(--text-secondary)] hover:text-[var(--foreground)]'
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
            graphData={graphData ?? null}
            onExpandChapter={onExpandChapter}
            onSeek={onSeek}
            onOpenModal={handleOpenModal}
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

      {/* Chapter Detail Modal */}
      {modalChapter && (
        <ChapterDetailModal
          open={!!modalChapter}
          onClose={() => setModalChapterId(null)}
          chapter={modalChapter}
          chapters={chapters}
          scenes={scenes}
          graphData={graphData}
          onSeek={onSeek}
          onNavigate={handleNavigateModal}
        />
      )}
    </>
  );
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */

/** Get entities connected to a chapter's scenes from graph data */
function getChapterEntities(
  chapter: Chapter,
  graphData: GraphVisualizationData | null,
): GraphNode[] {
  if (!graphData) return [];

  // Find the chapter node
  const chapterNode = graphData.nodes.find(
    (n) =>
      n.node_type === 'Chapter' &&
      (String(n.properties.chapter_id) === String(chapter.chapter_id) ||
        n.caption === chapter.title),
  );
  if (!chapterNode) return [];

  // Collect connected node IDs (2 hops: chapter→scene→entity)
  const hop1Ids = new Set<string>([chapterNode.id]);
  for (const rel of graphData.relationships) {
    if (rel.from === chapterNode.id || rel.to === chapterNode.id) {
      hop1Ids.add(rel.from);
      hop1Ids.add(rel.to);
    }
  }

  const entityIds = new Set<string>();
  for (const rel of graphData.relationships) {
    if (hop1Ids.has(rel.from) || hop1Ids.has(rel.to)) {
      const otherId = hop1Ids.has(rel.from) ? rel.to : rel.from;
      const other = graphData.nodes.find((n) => n.id === otherId);
      if (other && (other.node_type === 'Entity' || other.node_type === 'Topic')) {
        entityIds.add(otherId);
      }
    }
  }

  return graphData.nodes.filter((n) => entityIds.has(n.id));
}

/* ── Chapters tab ────────────────────────────────────────────────────────── */

function ChaptersContent({
  scenes,
  chapters,
  currentScene,
  expandedChapter,
  graphData,
  onExpandChapter,
  onSeek,
  onOpenModal,
}: {
  scenes: Scene[];
  chapters: Chapter[];
  currentScene?: Scene;
  expandedChapter: number | null;
  graphData: GraphVisualizationData | null;
  onExpandChapter: (id: number | null) => void;
  onSeek: (time: number) => void;
  onOpenModal: (chapterId: number) => void;
}) {
  if (chapters.length === 0 && scenes.length === 0) {
    return (
      <div className="p-3">
        <div className="text-center py-8">
          <Layers className="w-8 h-8 text-[var(--text-tertiary)] mx-auto mb-2" />
          <p className="text-sm text-[var(--text-secondary)]">No chapters available</p>
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
                isActive ? 'bg-indigo-50 border-l-4 border-indigo-500 dark:bg-indigo-500/10' : 'hover:bg-[var(--surface-elevated)]'
              }`}
            >
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                  isActive ? 'bg-indigo-500 text-white' : 'bg-[var(--surface-elevated)] text-[var(--text-secondary)]'
                }`}
              >
                <Play className="w-3 h-3 fill-current" />
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm truncate ${isActive ? 'font-semibold text-indigo-700 dark:text-indigo-400' : 'text-[var(--foreground)]'}`}>
                  {scene.title || `Scene ${scene.scene_id + 1}`}
                </p>
                <p className="text-xs text-[var(--text-tertiary)]">{formatTime(scene.start_time)}</p>
              </div>
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="p-3 space-y-2">
      {chapters.map((chapter) => (
        <ChapterCard
          key={chapter.chapter_id}
          chapter={chapter}
          scenes={scenes}
          currentScene={currentScene}
          isExpanded={expandedChapter === chapter.chapter_id}
          graphData={graphData}
          onToggle={() =>
            onExpandChapter(expandedChapter === chapter.chapter_id ? null : chapter.chapter_id)
          }
          onSeek={onSeek}
          onOpenModal={onOpenModal}
        />
      ))}
    </div>
  );
}

/* ── Chapter Card ────────────────────────────────────────────────────────── */

function ChapterCard({
  chapter,
  scenes,
  currentScene,
  isExpanded,
  graphData,
  onToggle,
  onSeek,
  onOpenModal,
}: {
  chapter: Chapter;
  scenes: Scene[];
  currentScene?: Scene;
  isExpanded: boolean;
  graphData: GraphVisualizationData | null;
  onToggle: () => void;
  onSeek: (time: number) => void;
  onOpenModal: (chapterId: number) => void;
}) {
  const chapterScenes = useMemo(
    () => scenes.filter((s) => chapter.scene_ids?.includes(s.scene_id)),
    [scenes, chapter.scene_ids],
  );

  const isActive = chapterScenes.some((s) => currentScene?.scene_id === s.scene_id);

  // Get summary from first scene
  const summaryPreview = useMemo(() => {
    const text = chapterScenes.find((s) => s.summary)?.summary;
    if (!text) return null;
    return text.length > 80 ? text.slice(0, 80) + '…' : text;
  }, [chapterScenes]);

  // Get entity pills from graph
  const entities = useMemo(
    () => getChapterEntities(chapter, graphData),
    [chapter, graphData],
  );
  const visibleEntities = entities.slice(0, 4);
  const extraCount = Math.max(0, entities.length - 4);

  return (
    <div className="rounded-xl overflow-hidden bg-[var(--surface)] border border-[var(--border)] transition-shadow hover:shadow-[var(--shadow-sm)]">
      {/* Card header */}
      <button
        onClick={onToggle}
        className={`w-full text-left p-3 flex items-start gap-3 transition-all ${
          isActive ? 'bg-indigo-50 dark:bg-indigo-500/10' : 'hover:bg-[var(--surface-elevated)]'
        }`}
      >
        <div className="pt-0.5">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-[var(--text-tertiary)]" />
          ) : (
            <ChevronRight className="w-4 h-4 text-[var(--text-tertiary)]" />
          )}
        </div>

        <div className="flex-1 min-w-0 space-y-1.5">
          {/* Title + time */}
          <div className="flex items-center justify-between gap-2">
            <p className={`text-sm font-medium truncate ${isActive ? 'text-indigo-700 dark:text-indigo-400' : 'text-[var(--foreground)]'}`}>
              {chapter.title}
            </p>
            <span className="text-xs text-[var(--text-tertiary)] shrink-0 tabular-nums">
              {formatTime(chapter.start_time)} — {formatTime(chapter.end_time)}
            </span>
          </div>

          {/* Summary preview */}
          {summaryPreview && (
            <p className="text-xs text-[var(--text-secondary)] leading-relaxed line-clamp-1">
              {summaryPreview}
            </p>
          )}

          {/* Entity pills + scene count + explore button */}
          <div className="flex items-center gap-2 flex-wrap">
            {visibleEntities.map((entity) => (
              <span
                key={entity.id}
                className="text-xs px-2 py-0.5 rounded-full"
                style={{
                  backgroundColor: entity.color + '20',
                  color: entity.color,
                  border: `1px solid ${entity.color}40`,
                }}
              >
                {entity.caption}
              </span>
            ))}
            {extraCount > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-[var(--surface-elevated)] text-[var(--text-tertiary)]">
                +{extraCount}
              </span>
            )}

            <span className="text-xs text-[var(--text-tertiary)] ml-auto shrink-0">
              {chapterScenes.length} scenes
            </span>

            <button
              onClick={(e) => {
                e.stopPropagation();
                onOpenModal(chapter.chapter_id);
              }}
              className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-violet-50 text-violet-700 hover:bg-violet-100 dark:bg-violet-500/10 dark:text-violet-400 dark:hover:bg-violet-500/20 transition-colors shrink-0"
            >
              <BarChart3 className="w-3 h-3" />
              Explore
            </button>
          </div>
        </div>

        <button
          onClick={(e) => {
            e.stopPropagation();
            onSeek(chapter.start_time);
          }}
          className="p-1.5 hover:bg-indigo-100 dark:hover:bg-indigo-500/20 rounded-lg text-indigo-500 shrink-0"
          aria-label="Play chapter"
        >
          <Play className="w-3 h-3 fill-current" />
        </button>
      </button>

      {/* Expanded scene list */}
      {isExpanded && chapterScenes.length > 0 && (
        <div className="px-3 pb-3 space-y-1 border-t border-[var(--border-subtle)]">
          <div className="pt-2" />
          {chapterScenes.map((scene) => {
            const isSceneActive = currentScene?.scene_id === scene.scene_id;
            return (
              <button
                key={scene.scene_id}
                onClick={() => onSeek(scene.start_time)}
                className={`w-full text-left pl-8 pr-3 py-2 rounded-lg transition-all text-sm ${
                  isSceneActive
                    ? 'bg-indigo-100 text-indigo-700 font-medium dark:bg-indigo-500/15 dark:text-indigo-400'
                    : 'text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)]'
                }`}
              >
                <span className="text-[var(--text-tertiary)] mr-2">{formatTime(scene.start_time)}</span>
                {scene.title || `Scene ${scene.scene_id + 1}`}
              </button>
            );
          })}
        </div>
      )}
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
          <Mic className="w-8 h-8 text-[var(--text-tertiary)] mx-auto mb-2" />
          <p className="text-sm text-[var(--text-secondary)]">No transcript available</p>
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
              isActive ? 'bg-indigo-50 border-l-4 border-indigo-500 dark:bg-indigo-500/10' : 'hover:bg-[var(--surface-elevated)]'
            }`}
          >
            <span className="text-xs text-indigo-500 font-medium dark:text-indigo-400">
              {formatTime(segment.start)}
            </span>
            <p className={`text-sm mt-1 ${isActive ? 'text-indigo-700 font-medium dark:text-indigo-400' : 'text-[var(--foreground)]'}`}>
              {segment.text}
            </p>
          </button>
        );
      })}
    </div>
  );
}
