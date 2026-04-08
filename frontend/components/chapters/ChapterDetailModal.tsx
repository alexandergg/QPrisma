'use client';

import React, { useCallback, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  ChevronLeft,
  ChevronRight,
  Play,
  Clock,
  Film,
  Tag,
} from 'lucide-react';
import { formatTime } from '@/lib/utils';
import { ChapterMiniGraph } from './ChapterMiniGraph';
import type { GraphNode, GraphRelationship, GraphVisualizationData, Scene, Chapter } from '@/types';

/* ── Props ──────────────────────────────────────────────────────────────── */

interface ChapterDetailModalProps {
  open: boolean;
  onClose: () => void;
  chapter: Chapter;
  chapters: Chapter[];
  scenes: Scene[];
  graphData?: GraphVisualizationData | null;
  onSeek: (time: number) => void;
  onNavigate: (chapterId: number) => void;
}

/* ── Component ──────────────────────────────────────────────────────────── */

export function ChapterDetailModal({
  open,
  onClose,
  chapter,
  chapters,
  scenes,
  graphData,
  onSeek,
  onNavigate,
}: ChapterDetailModalProps) {
  // Keyboard: Escape to close, arrow keys to navigate
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft') navigatePrev();
      if (e.key === 'ArrowRight') navigateNext();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, chapter.chapter_id]);

  // Lock body scroll
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  /* ── Navigation ─────────────────────────────────────────────────────── */

  const currentIdx = chapters.findIndex((c) => c.chapter_id === chapter.chapter_id);
  const hasPrev = currentIdx > 0;
  const hasNext = currentIdx < chapters.length - 1;

  const navigatePrev = useCallback(() => {
    if (hasPrev) onNavigate(chapters[currentIdx - 1].chapter_id);
  }, [hasPrev, currentIdx, chapters, onNavigate]);

  const navigateNext = useCallback(() => {
    if (hasNext) onNavigate(chapters[currentIdx + 1].chapter_id);
  }, [hasNext, currentIdx, chapters, onNavigate]);

  /* ── Chapter scenes ─────────────────────────────────────────────────── */

  const chapterScenes = useMemo(
    () => scenes.filter((s) => chapter.scene_ids?.includes(s.scene_id)),
    [scenes, chapter.scene_ids],
  );

  const chapterDuration = chapter.end_time - chapter.start_time;

  // Build summary from scene summaries or transcript segments
  const summaryText = useMemo(() => {
    const parts = chapterScenes
      .map((s) => s.summary)
      .filter(Boolean);
    return parts.length > 0 ? parts.join(' ') : null;
  }, [chapterScenes]);

  /* ── Graph filtering ────────────────────────────────────────────────── */

  const { filteredNodes, filteredRels, entitiesByType } = useMemo(() => {
    if (!graphData) return { filteredNodes: [], filteredRels: [], entitiesByType: new Map<string, GraphNode[]>() };

    // Find the chapter node
    const chapterNode = graphData.nodes.find(
      (n) =>
        n.node_type === 'Chapter' &&
        (String(n.properties.chapter_id) === String(chapter.chapter_id) ||
          n.caption === chapter.title),
    );

    if (!chapterNode) return { filteredNodes: [], filteredRels: [], entitiesByType: new Map<string, GraphNode[]>() };

    // Collect all nodes reachable from this chapter (2 hops: chapter→scene→entity)
    const nodeIds = new Set<string>([chapterNode.id]);
    const relevantRels: GraphRelationship[] = [];

    // Hop 1: chapter → scenes
    for (const rel of graphData.relationships) {
      if (rel.from === chapterNode.id || rel.to === chapterNode.id) {
        nodeIds.add(rel.from);
        nodeIds.add(rel.to);
        relevantRels.push(rel);
      }
    }

    // Hop 2: scenes → entities/topics
    const hop1Ids = new Set(nodeIds);
    for (const rel of graphData.relationships) {
      if (
        (hop1Ids.has(rel.from) || hop1Ids.has(rel.to)) &&
        !relevantRels.includes(rel)
      ) {
        const otherNodeId = hop1Ids.has(rel.from) ? rel.to : rel.from;
        const otherNode = graphData.nodes.find((n) => n.id === otherNodeId);
        // Only include entities and topics from hop 2
        if (
          otherNode &&
          (otherNode.node_type === 'Entity' || otherNode.node_type === 'Topic')
        ) {
          nodeIds.add(rel.from);
          nodeIds.add(rel.to);
          relevantRels.push(rel);
        }
      }
    }

    const fNodes = graphData.nodes.filter((n) => nodeIds.has(n.id));
    const fRels = relevantRels;

    // Group entities by type for the left panel
    const byType = new Map<string, GraphNode[]>();
    for (const n of fNodes) {
      if (n.node_type === 'Entity' || n.node_type === 'Topic') {
        const key = n.entity_type || n.node_type.toLowerCase();
        const list = byType.get(key) ?? [];
        list.push(n);
        byType.set(key, list);
      }
    }

    return { filteredNodes: fNodes, filteredRels: fRels, entitiesByType: byType };
  }, [graphData, chapter.chapter_id, chapter.title]);

  /* ── Tooltip state for graph node click ─────────────────────────────── */

  const [tooltipNode, setTooltipNode] = React.useState<GraphNode | null>(null);

  const handleGraphNodeClick = useCallback((node: GraphNode) => {
    setTooltipNode((prev) => (prev?.id === node.id ? null : node));
  }, []);

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
          role="dialog"
          aria-modal="true"
          aria-label={`Chapter: ${chapter.title}`}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ duration: 0.2, ease: [0.34, 1.56, 0.64, 1] }}
            className="relative w-full max-w-4xl mx-4 max-h-[85vh] bg-[var(--surface)] rounded-[var(--radius-xl)] shadow-[var(--shadow-xl)] flex flex-col overflow-hidden"
          >
            {/* ── Header ────────────────────────────────────────────── */}
            <div className="flex items-center gap-3 px-5 py-4 border-b border-[var(--border-subtle)] shrink-0">
              <button
                onClick={navigatePrev}
                disabled={!hasPrev}
                className="p-1.5 rounded-[var(--radius-md)] text-[var(--text-tertiary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--foreground)] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                aria-label="Previous chapter"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>

              <div className="flex-1 min-w-0">
                <h2 className="text-base font-semibold text-[var(--foreground)] truncate">
                  Chapter {currentIdx + 1}: {chapter.title}
                </h2>
                <p className="text-xs text-[var(--text-tertiary)]">
                  {formatTime(chapter.start_time)} — {formatTime(chapter.end_time)}
                </p>
              </div>

              <button
                onClick={navigateNext}
                disabled={!hasNext}
                className="p-1.5 rounded-[var(--radius-md)] text-[var(--text-tertiary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--foreground)] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                aria-label="Next chapter"
              >
                <ChevronRight className="w-4 h-4" />
              </button>

              <div className="w-px h-6 bg-[var(--border-subtle)]" />

              <button
                onClick={onClose}
                className="p-1.5 rounded-[var(--radius-md)] text-[var(--text-tertiary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--foreground)] transition-colors"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* ── Body ──────────────────────────────────────────────── */}
            <div className="flex flex-1 min-h-0 overflow-hidden">
              {/* Left panel: chapter info */}
              <div className="w-1/2 border-r border-[var(--border-subtle)] overflow-y-auto p-5 space-y-5">
                {/* Summary */}
                {summaryText && (
                  <section>
                    <h3 className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide mb-2">
                      <Film className="w-3.5 h-3.5" />
                      Summary
                    </h3>
                    <p className="text-sm text-[var(--foreground)] leading-relaxed">
                      {summaryText}
                    </p>
                  </section>
                )}

                {/* Scenes */}
                <section>
                  <h3 className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide mb-2">
                    <Film className="w-3.5 h-3.5" />
                    Scenes ({chapterScenes.length})
                  </h3>
                  <div className="space-y-1">
                    {chapterScenes.map((scene) => (
                      <button
                        key={scene.scene_id}
                        onClick={() => onSeek(scene.start_time)}
                        className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-[var(--radius-md)] text-sm hover:bg-[var(--surface-elevated)] transition-colors group"
                      >
                        <Play className="w-3 h-3 text-[var(--text-tertiary)] group-hover:text-[var(--amber-8)] shrink-0" />
                        <span className="flex-1 truncate text-[var(--foreground)]">
                          {scene.title || `Scene ${scene.scene_id + 1}`}
                        </span>
                        <span className="text-xs text-[var(--text-tertiary)] shrink-0">
                          {formatTime(scene.start_time)}
                        </span>
                      </button>
                    ))}
                  </div>
                </section>

                {/* Entities grouped by type */}
                {entitiesByType.size > 0 && (
                  <section>
                    <h3 className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide mb-2">
                      <Tag className="w-3.5 h-3.5" />
                      Entities
                    </h3>
                    <div className="space-y-2">
                      {Array.from(entitiesByType.entries()).map(([type, entityNodes]) => (
                        <div key={type}>
                          <span className="text-xs text-[var(--text-tertiary)] capitalize">{type}</span>
                          <div className="flex flex-wrap gap-1.5 mt-1">
                            {entityNodes.map((n) => (
                              <span
                                key={n.id}
                                className="text-xs px-2 py-0.5 rounded-full"
                                style={{
                                  backgroundColor: n.color + '20',
                                  color: n.color,
                                  border: `1px solid ${n.color}40`,
                                }}
                              >
                                {n.caption}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </div>

              {/* Right panel: mini knowledge graph */}
              <div className="w-1/2 flex flex-col bg-[var(--surface-elevated)] relative">
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--border-subtle)]">
                  <span className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide">
                    Knowledge Graph
                  </span>
                  {filteredNodes.length > 0 && (
                    <span className="text-xs text-[var(--text-tertiary)]">
                      {filteredNodes.length} nodes
                    </span>
                  )}
                </div>
                <div className="flex-1 min-h-0 p-3">
                  <ChapterMiniGraph
                    nodes={filteredNodes}
                    relationships={filteredRels}
                    onNodeClick={handleGraphNodeClick}
                    className="h-full"
                  />
                </div>

                {/* Node tooltip */}
                <AnimatePresence>
                  {tooltipNode && (
                    <motion.div
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: 4 }}
                      transition={{ duration: 0.12 }}
                      className="absolute bottom-4 left-4 right-4 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-md)] shadow-[var(--shadow-md)] p-3 text-xs"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <div
                          className="w-3 h-3 rounded-full shrink-0"
                          style={{ backgroundColor: tooltipNode.color }}
                        />
                        <span className="font-semibold text-[var(--foreground)]">
                          {tooltipNode.caption}
                        </span>
                        <button
                          onClick={() => setTooltipNode(null)}
                          className="ml-auto p-0.5 text-[var(--text-tertiary)] hover:text-[var(--foreground)]"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                      <p className="text-[var(--text-secondary)]">
                        {tooltipNode.node_type}
                        {tooltipNode.entity_type ? ` · ${tooltipNode.entity_type}` : ''}
                      </p>
                      {tooltipNode.properties.description != null && (
                        <p className="text-[var(--text-secondary)] mt-1 line-clamp-2">
                          {String(tooltipNode.properties.description)}
                        </p>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </div>

            {/* ── Footer ────────────────────────────────────────────── */}
            <div className="flex items-center justify-between px-5 py-3 border-t border-[var(--border-subtle)] shrink-0">
              <button
                onClick={() => onSeek(chapter.start_time)}
                className="flex items-center gap-2 px-4 py-2 rounded-[var(--radius-md)] bg-[var(--amber-3)] text-[var(--amber-11,var(--foreground))] hover:bg-[var(--amber-4)] text-sm font-medium transition-colors"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                Play Chapter
              </button>
              <div className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
                <Clock className="w-3.5 h-3.5" />
                {formatTime(chapterDuration)} duration
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
