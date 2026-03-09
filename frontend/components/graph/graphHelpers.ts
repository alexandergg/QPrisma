import type { Node, Relationship } from '@neo4j-nvl/base';
import type { GraphNode, GraphRelationship } from '@/types';

/** Map a backend GraphNode to the NVL Node type. */
export function toNvlNode(g: GraphNode): Node {
  return {
    id: g.id,
    caption: g.caption,
    color: g.color,
    size: g.size,
    pinned: false,
  };
}

/** Map a backend GraphRelationship to the NVL Relationship type. */
export function toNvlRel(g: GraphRelationship): Relationship {
  return {
    id: g.id,
    from: g.from,
    to: g.to,
    caption: g.caption,
    type: g.type,
    color: g.color || '#94A3B8',
  };
}
