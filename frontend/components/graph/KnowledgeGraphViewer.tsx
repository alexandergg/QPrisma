'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { InteractiveNvlWrapper } from '@neo4j-nvl/react';
import type { Node, HitTargets } from '@neo4j-nvl/base';
import type { MouseEventCallbacks } from '@neo4j-nvl/react';
import { Loader2, AlertCircle, Maximize2, Minimize2, Share2 } from 'lucide-react';
import { GraphControls } from './GraphControls';
import { GraphLegend } from './GraphLegend';
import { NodeDetailPanel } from './NodeDetailPanel';
import { useGraphData } from './useGraphData';
import type { GraphNode } from '@/types';

// ============================================================================
// Props
// ============================================================================

interface KnowledgeGraphViewerProps {
  videoId: string;
  onSeek?: (time: number) => void;
  className?: string;
}

// ============================================================================
// Component
// ============================================================================

export default function KnowledgeGraphViewer({
  videoId,
  onSeek,
  className = '',
}: KnowledgeGraphViewerProps) {
  // ── State ────────────────────────────────────────────────────────────────
  const [depth, setDepth] = useState(2);
  const [layout, setLayout] = useState<'forceDirected' | 'd3Force'>('forceDirected');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nvlRef = useRef<any>(null);

  // ── Data ─────────────────────────────────────────────────────────────────
  const {
    data,
    error,
    isLoading,
    nvlNodes,
    nvlRels,
    nodeMapRef,
    expandNode,
    resetExpanded,
  } = useGraphData(videoId, depth);

  // ── Handlers ─────────────────────────────────────────────────────────────

  /**
   * On node click: select + seek to timestamp. Double-click expands subgraph.
   */
  const handleNodeClick = useCallback(
    (node: Node) => {
      const gNode = nodeMapRef.current.get(node.id) ?? null;
      setSelectedNode(gNode);

      if (!gNode || !onSeek) return;

      const props = gNode.properties;
      const timestamp =
        (props.timestamp as number | undefined) ??
        (props.start_time as number | undefined);

      if (timestamp != null) {
        onSeek(timestamp);
      }
    },
    [onSeek, nodeMapRef],
  );

  const handleNodeDoubleClick = useCallback(
    async (node: Node) => {
      await expandNode(node.id);
    },
    [expandNode],
  );

  const mouseCallbacks: MouseEventCallbacks = {
    onNodeClick: (node: Node, _hitElements: HitTargets, _event: MouseEvent) => {
      handleNodeClick(node);
    },
    onNodeDoubleClick: (node: Node, _hitElements: HitTargets, _event: MouseEvent) => {
      handleNodeDoubleClick(node);
    },
    onCanvasClick: () => {
      setSelectedNode(null);
    },
    onDrag: true,
    onHover: true,
  };

  // ── Fullscreen toggle ────────────────────────────────────────────────────
  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((prev) => !prev);
  }, []);

  // Fit graph to viewport after data loads
  useEffect(() => {
    if (nvlNodes.length > 0 && nvlRef.current?.fit) {
      // Small delay to let the layout settle
      const timer = setTimeout(() => {
        nvlRef.current?.fit?.();
      }, 800);
      return () => clearTimeout(timer);
    }
  }, [nvlNodes.length]);

  // ── Depth change (resets expanded state) ─────────────────────────────────
  const handleDepthChange = useCallback((newDepth: number) => {
    setDepth(newDepth);
    resetExpanded();
    setSelectedNode(null);
  }, [resetExpanded]);

  // ── Layout change ────────────────────────────────────────────────────────
  const handleLayoutChange = useCallback((newLayout: 'forceDirected' | 'd3Force') => {
    setLayout(newLayout);
  }, []);

  // ── Zoom reset ───────────────────────────────────────────────────────────
  const handleZoomReset = useCallback(() => {
    nvlRef.current?.fit?.();
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────
  // Error state
  if (error) {
    return (
      <div className={`flex flex-col items-center justify-center h-full text-center p-6 ${className}`}>
        <AlertCircle className="w-10 h-10 text-[var(--rose-7)] mb-3" />
        <p className="text-[var(--foreground)] font-medium">Failed to load graph</p>
        <p className="text-[var(--text-tertiary)] text-sm mt-1">
          {error instanceof Error ? error.message : 'The Knowledge Graph may not be available for this video'}
        </p>
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <div className={`flex flex-col items-center justify-center h-full ${className}`}>
        <Loader2 className="w-8 h-8 text-[var(--amber-8)] animate-spin mb-3" />
        <p className="text-[var(--text-secondary)] text-sm">Loading Knowledge Graph...</p>
      </div>
    );
  }

  // Empty state
  if (!data || nvlNodes.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center h-full text-center p-6 ${className}`}>
        <Share2 className="w-10 h-10 text-[var(--text-tertiary)] mb-3" />
        <p className="text-[var(--text-secondary)] font-medium">No graph data</p>
        <p className="text-[var(--text-tertiary)] text-sm mt-1">
          Process the video to build the Knowledge Graph
        </p>
      </div>
    );
  }

  const wrapperClasses = isFullscreen
    ? 'fixed inset-0 z-50 bg-[var(--surface)] flex flex-col'
    : `flex flex-col h-full ${className}`;

  return (
    <div className={wrapperClasses} ref={containerRef}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)] bg-[var(--surface)] shrink-0">
        <div className="flex items-center gap-2">
          <Share2 className="w-4 h-4 text-[var(--amber-8)]" />
          <span className="font-semibold text-[var(--foreground)] text-sm">Knowledge Graph</span>
          <span className="text-xs text-[var(--text-tertiary)]">
            {nvlNodes.length} nodes · {nvlRels.length} rels
          </span>
        </div>
        <div className="flex items-center gap-1">
          <GraphControls
            depth={depth}
            layout={layout}
            onDepthChange={handleDepthChange}
            onLayoutChange={handleLayoutChange}
            onZoomReset={handleZoomReset}
          />
          <button
            onClick={toggleFullscreen}
            className="p-1.5 rounded-lg hover:bg-[var(--surface-elevated)] text-[var(--text-secondary)] hover:text-[var(--foreground)] transition-colors"
            title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          >
            {isFullscreen ? (
              <Minimize2 className="w-4 h-4" />
            ) : (
              <Maximize2 className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Graph canvas */}
      <div className="relative flex-1 min-h-0">
        <InteractiveNvlWrapper
          ref={nvlRef}
          nodes={nvlNodes}
          rels={nvlRels}
          layout={layout}
          mouseEventCallbacks={mouseCallbacks}
          interactionOptions={{
            selectOnClick: true,
            drawShadowOnHover: true,
          }}
          nvlOptions={{
            allowDynamicMinZoom: true,
            disableWebGL: false,
            renderer: 'canvas',
          }}
          style={{ width: '100%', height: '100%' }}
        />

        {/* Legend overlay */}
        <GraphLegend className="absolute bottom-2 left-2" />

        {/* Selected node detail panel */}
        {selectedNode && (
          <NodeDetailPanel selectedNode={selectedNode} onSeek={onSeek} />
        )}
      </div>
    </div>
  );
}
