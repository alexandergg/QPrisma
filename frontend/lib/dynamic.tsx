/**
 * Dynamic imports for code splitting
 *
 * Keep this file focused on heavy components that are mounted by active routes.
 */

import dynamic from 'next/dynamic';

// ============================================================================
// Visualization Components
// ============================================================================

/**
 * Knowledge Graph Viewer - Neo4j NVL based graph visualization
 */
export const DynamicKnowledgeGraphViewer = dynamic(
  () => import('@/components/graph/KnowledgeGraphViewer'),
  {
    loading: () => (
      <div className="h-full bg-gray-50 rounded-lg animate-pulse flex items-center justify-center">
        <span className="text-gray-400">Loading Knowledge Graph...</span>
      </div>
    ),
    ssr: false,
  }
);
