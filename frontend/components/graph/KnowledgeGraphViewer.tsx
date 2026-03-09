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
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

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
      setSelectedNodeId(node.id);

      const gNode = nodeMapRef.current.get(node.id);
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
      setSelectedNodeId(null);
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
    setSelectedNodeId(null);
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
        <AlertCircle className="w-10 h-10 text-red-400 mb-3" />
        <p className="text-gray-700 font-medium">Failed to load graph</p>
        <p className="text-gray-400 text-sm mt-1">
          {error instanceof Error ? error.message : 'The Knowledge Graph may not be available for this video'}
        </p>
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <div className={`flex flex-col items-center justify-center h-full ${className}`}>
        <Loader2 className="w-8 h-8 text-indigo-500 animate-spin mb-3" />
        <p className="text-gray-500 text-sm">Loading Knowledge Graph...</p>
      </div>
    );
  }

  // Empty state
  if (!data || nvlNodes.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center h-full text-center p-6 ${className}`}>
        <Share2 className="w-10 h-10 text-gray-300 mb-3" />
        <p className="text-gray-500 font-medium">No graph data</p>
        <p className="text-gray-400 text-sm mt-1">
          Process the video to build the Knowledge Graph
        </p>
      </div>
    );
  }

  // Selected node info panel
  const selectedNode = selectedNodeId
    ? nodeMapRef.current.get(selectedNodeId)
    : null;

  const wrapperClasses = isFullscreen
    ? 'fixed inset-0 z-50 bg-white flex flex-col'
    : `flex flex-col h-full ${className}`;

  return (
    <div className={wrapperClasses} ref={containerRef}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 bg-white shrink-0">
        <div className="flex items-center gap-2">
          <Share2 className="w-4 h-4 text-indigo-500" />
          <span className="font-semibold text-gray-900 text-sm">Knowledge Graph</span>
          <span className="text-xs text-gray-400">
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
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors"
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
