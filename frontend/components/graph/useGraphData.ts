'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import useSWR from 'swr';
import type { Node, Relationship } from '@neo4j-nvl/base';
import { apiClient } from '@/lib/api';
import type {
  GraphVisualizationData,
  GraphExpandResult,
  GraphNode,
  GraphRelationship,
} from '@/types';
import { toNvlNode, toNvlRel } from './graphHelpers';

/**
 * Hook for fetching and managing knowledge graph data.
 *
 * Handles initial fetch, deduplication, and on-demand node expansion.
 * Returns NVL-compatible node/relationship arrays and a lookup map.
 */
export function useGraphData(videoId: string, depth: number) {
  const [extraNodes, setExtraNodes] = useState<GraphNode[]>([]);
  const [extraRels, setExtraRels] = useState<GraphRelationship[]>([]);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  /** Lookup map: node-id → backend GraphNode (for property access). */
  const nodeMapRef = useRef<Map<string, GraphNode>>(new Map());

  // ── SWR fetch ────────────────────────────────────────────────────────────
  const { data, error, isLoading } = useSWR<GraphVisualizationData>(
    videoId ? `graph-viz-${videoId}-${depth}` : null,
    () => apiClient.getVideoVisualization(videoId, { depth }),
    { revalidateOnFocus: false },
  );

  // ── Build combined + deduplicated NVL arrays ─────────────────────────────
  const allGraphNodes = [...(data?.nodes ?? []), ...extraNodes];
  const allGraphRels = [...(data?.relationships ?? []), ...extraRels];

  const nodeById = new Map<string, GraphNode>();
  for (const n of allGraphNodes) nodeById.set(n.id, n);
  const relById = new Map<string, GraphRelationship>();
  for (const r of allGraphRels) relById.set(r.id, r);

  const nvlNodes: Node[] = Array.from(nodeById.values()).map(toNvlNode);
  const nvlRels: Relationship[] = Array.from(relById.values()).map(toNvlRel);

  // Keep the lookup map in sync
  useEffect(() => {
    nodeMapRef.current = nodeById;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allGraphNodes.length]);

  // ── Expand a node (double-click) ─────────────────────────────────────────
  const expandNode = useCallback(
    async (nodeId: string) => {
      if (expandedNodes.has(nodeId)) return;

      try {
        const result: GraphExpandResult = await apiClient.expandGraphNode(nodeId, 1, 50);
        setExtraNodes((prev) => [...prev, ...result.nodes]);
        setExtraRels((prev) => [...prev, ...result.relationships]);
        setExpandedNodes((prev) => new Set([...prev, nodeId]));
      } catch (err) {
        console.error('Graph expand failed:', err);
      }
    },
    [expandedNodes],
  );

  // ── Reset expansion when depth changes ───────────────────────────────────
  const resetExpanded = useCallback(() => {
    setExtraNodes([]);
    setExtraRels([]);
    setExpandedNodes(new Set());
  }, []);

  return {
    data,
    error,
    isLoading,
    nvlNodes,
    nvlRels,
    nodeMapRef,
    expandNode,
    resetExpanded,
  };
}
