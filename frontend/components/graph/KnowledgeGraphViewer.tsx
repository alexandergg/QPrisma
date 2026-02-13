'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { InteractiveNvlWrapper } from '@neo4j-nvl/react';
import type { Node, Relationship, HitTargets } from '@neo4j-nvl/base';
import type { MouseEventCallbacks } from '@neo4j-nvl/react';
import useSWR from 'swr';
import { Loader2, AlertCircle, Maximize2, Minimize2, Share2 } from 'lucide-react';
import { apiClient } from '@/lib/api';
import type {
  GraphVisualizationData,
  GraphExpandResult,
  GraphNode,
  GraphRelationship,
} from '@/types';
import { GraphControls } from './GraphControls';
import { GraphLegend } from './GraphLegend';

// ============================================================================
// Helpers: Map backend data → NVL types
// ============================================================================

function toNvlNode(g: GraphNode): Node {
  return {
    id: g.id,
    caption: g.caption,
    color: g.color,
    size: g.size,
    pinned: false,
  };
}

function toNvlRel(g: GraphRelationship): Relationship {
  return {
    id: g.id,
    from: g.from,
    to: g.to,
    caption: g.caption,
    type: g.type,
    color: g.color || '#94A3B8',
  };
}

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
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  // Extra nodes/rels added via expand-on-click
  const [extraNodes, setExtraNodes] = useState<GraphNode[]>([]);
  const [extraRels, setExtraRels] = useState<GraphRelationship[]>([]);

  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nvlRef = useRef<any>(null);

  // Map from node id → backend GraphNode for property lookups
  const nodeMapRef = useRef<Map<string, GraphNode>>(new Map());

  // ── Data Fetching ────────────────────────────────────────────────────────
  const { data, error, isLoading } = useSWR<GraphVisualizationData>(
    videoId ? `graph-viz-${videoId}-${depth}` : null,
    () => apiClient.getVideoVisualization(videoId, { depth }),
    { revalidateOnFocus: false }
  );

  // Build combined NVL nodes & rels (initial + expanded)
  const allGraphNodes = [...(data?.nodes ?? []), ...extraNodes];
  const allGraphRels = [...(data?.relationships ?? []), ...extraRels];

  // Deduplicate by id
  const nodeById = new Map<string, GraphNode>();
  for (const n of allGraphNodes) nodeById.set(n.id, n);
  const relById = new Map<string, GraphRelationship>();
  for (const r of allGraphRels) relById.set(r.id, r);

  const nvlNodes: Node[] = Array.from(nodeById.values()).map(toNvlNode);
  const nvlRels: Relationship[] = Array.from(relById.values()).map(toNvlRel);

  // Update node lookup map
  useEffect(() => {
    nodeMapRef.current = nodeById;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allGraphNodes.length]);

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
    [onSeek]
  );

  const handleNodeDoubleClick = useCallback(
    async (node: Node) => {
      if (expandedNodes.has(node.id)) return;

      try {
        const result: GraphExpandResult = await apiClient.expandGraphNode(
          node.id,
          1,
          50
        );

        setExtraNodes((prev) => [...prev, ...result.nodes]);
        setExtraRels((prev) => [...prev, ...result.relationships]);
        setExpandedNodes((prev) => new Set([...prev, node.id]));
      } catch (err) {
        console.error('Graph expand failed:', err);
      }
    },
    [expandedNodes]
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
    // Enable drag-to-move nodes (pass true to use default behavior)
    onDrag: true,
    // Enable hover highlight
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
    setExtraNodes([]);
    setExtraRels([]);
    setExpandedNodes(new Set());
    setSelectedNodeId(null);
  }, []);

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
          <div className="absolute top-2 right-2 w-56 bg-white/95 backdrop-blur rounded-lg shadow-lg border border-gray-200 p-3 text-xs">
            <div className="flex items-center gap-2 mb-2">
              <div
                className="w-3 h-3 rounded-full shrink-0"
                style={{ backgroundColor: selectedNode.color }}
              />
              <span className="font-semibold text-gray-900 truncate">
                {selectedNode.caption}
              </span>
            </div>
            <div className="space-y-1 text-gray-500">
              <p>
                <span className="text-gray-700 font-medium">Type:</span>{' '}
                {selectedNode.node_type}
                {selectedNode.entity_type ? ` (${selectedNode.entity_type})` : ''}
              </p>
              {selectedNode.properties.description != null && (
                <p className="line-clamp-3">
                  {String(selectedNode.properties.description)}
                </p>
              )}
              {selectedNode.properties.timestamp != null && (
                <p>
                  <span className="text-gray-700 font-medium">Time:</span>{' '}
                  {Number(selectedNode.properties.timestamp).toFixed(1)}s
                </p>
              )}
              {selectedNode.properties.start_time != null && (
                <p>
                  <span className="text-gray-700 font-medium">Range:</span>{' '}
                  {Number(selectedNode.properties.start_time).toFixed(1)}s –{' '}
                  {Number(selectedNode.properties.end_time).toFixed(1)}s
                </p>
              )}
            </div>
            {onSeek && selectedNode.properties.timestamp != null && (
              <button
                onClick={() => onSeek(Number(selectedNode.properties.timestamp))}
                className="mt-2 w-full text-center text-indigo-600 hover:text-indigo-700 font-medium"
              >
                Seek to timestamp →
              </button>
            )}
            {onSeek && selectedNode.properties.start_time != null && !selectedNode.properties.timestamp && (
              <button
                onClick={() => onSeek(Number(selectedNode.properties.start_time))}
                className="mt-2 w-full text-center text-indigo-600 hover:text-indigo-700 font-medium"
              >
                Seek to start →
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
