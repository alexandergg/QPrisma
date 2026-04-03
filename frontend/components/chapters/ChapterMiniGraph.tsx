'use client';

import React, { useMemo } from 'react';
import type { GraphNode, GraphRelationship } from '@/types';

interface ChapterMiniGraphProps {
  nodes: GraphNode[];
  relationships: GraphRelationship[];
  onNodeClick?: (node: GraphNode) => void;
  className?: string;
}

/**
 * Lightweight SVG-based graph for the chapter detail modal.
 * Uses a radial layout centred on the Chapter node.
 */
export function ChapterMiniGraph({
  nodes,
  relationships,
  onNodeClick,
  className = '',
}: ChapterMiniGraphProps) {
  const layout = useMemo(() => computeLayout(nodes, relationships), [nodes, relationships]);

  if (nodes.length === 0) {
    return (
      <div className={`flex items-center justify-center h-full text-[var(--text-tertiary)] text-sm ${className}`}>
        No graph data for this chapter
      </div>
    );
  }

  return (
    <svg
      viewBox="-200 -200 400 400"
      className={`w-full h-full ${className}`}
      style={{ minHeight: 220 }}
    >
      {/* Edges */}
      {layout.edges.map((edge) => (
        <line
          key={edge.id}
          x1={edge.x1}
          y1={edge.y1}
          x2={edge.x2}
          y2={edge.y2}
          stroke="var(--border)"
          strokeWidth={1}
          strokeOpacity={0.6}
        />
      ))}

      {/* Nodes */}
      {layout.positioned.map((item) => {
        const r = item.radius;
        return (
          <g
            key={item.node.id}
            transform={`translate(${item.x}, ${item.y})`}
            onClick={() => onNodeClick?.(item.node)}
            className="cursor-pointer"
          >
            <circle
              r={r}
              fill={item.node.color}
              opacity={0.85}
              className="transition-opacity hover:opacity-100"
            />
            <text
              y={r + 12}
              textAnchor="middle"
              className="fill-[var(--foreground)] text-[9px] pointer-events-none"
              style={{ fontSize: 9 }}
            >
              {truncate(item.node.caption, 14)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ── Layout helpers ─────────────────────────────────────────────────────── */

interface PositionedNode {
  node: GraphNode;
  x: number;
  y: number;
  radius: number;
}

interface PositionedEdge {
  id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function radiusForType(type: string): number {
  switch (type) {
    case 'Chapter':
      return 18;
    case 'Scene':
      return 13;
    default:
      return 9;
  }
}

function computeLayout(
  nodes: GraphNode[],
  relationships: GraphRelationship[],
): { positioned: PositionedNode[]; edges: PositionedEdge[] } {
  if (nodes.length === 0) return { positioned: [], edges: [] };

  // Place center node (Chapter or first)
  const center = nodes.find((n) => n.node_type === 'Chapter') ?? nodes[0];
  const others = nodes.filter((n) => n.id !== center.id);

  // Group by ring: scenes close, entities/topics further
  const scenes = others.filter((n) => n.node_type === 'Scene');
  const rest = others.filter((n) => n.node_type !== 'Scene');

  const positioned: PositionedNode[] = [
    { node: center, x: 0, y: 0, radius: radiusForType(center.node_type) },
  ];

  const posMap = new Map<string, { x: number; y: number }>();
  posMap.set(center.id, { x: 0, y: 0 });

  // Ring 1: scenes
  const r1 = scenes.length <= 4 ? 70 : 90;
  placeRing(scenes, r1, positioned, posMap);

  // Ring 2: entities/topics
  const r2 = rest.length <= 8 ? 145 : 165;
  placeRing(rest, r2, positioned, posMap);

  // Build edges
  const edges: PositionedEdge[] = [];
  for (const rel of relationships) {
    const from = posMap.get(rel.from);
    const to = posMap.get(rel.to);
    if (from && to) {
      edges.push({ id: rel.id, x1: from.x, y1: from.y, x2: to.x, y2: to.y });
    }
  }

  return { positioned, edges };
}

function placeRing(
  nodes: GraphNode[],
  radius: number,
  out: PositionedNode[],
  posMap: Map<string, { x: number; y: number }>,
) {
  const count = nodes.length;
  if (count === 0) return;

  const angleStep = (2 * Math.PI) / count;
  const offset = -Math.PI / 2; // start at top

  for (let i = 0; i < count; i++) {
    const angle = offset + i * angleStep;
    const x = Math.cos(angle) * radius;
    const y = Math.sin(angle) * radius;
    out.push({ node: nodes[i], x, y, radius: radiusForType(nodes[i].node_type) });
    posMap.set(nodes[i].id, { x, y });
  }
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max - 1) + '…' : str;
}
