'use client';

import { RotateCcw, Layers, GitBranch } from 'lucide-react';

// ============================================================================
// Types
// ============================================================================

interface GraphControlsProps {
  depth: number;
  layout: 'forceDirected' | 'd3Force';
  onDepthChange: (depth: number) => void;
  onLayoutChange: (layout: 'forceDirected' | 'd3Force') => void;
  onZoomReset: () => void;
}

// ============================================================================
// Component
// ============================================================================

export function GraphControls({
  depth,
  layout,
  onDepthChange,
  onLayoutChange,
  onZoomReset,
}: GraphControlsProps) {
  return (
    <div className="flex items-center gap-1">
      {/* Depth selector */}
      <div className="flex items-center gap-1 mr-1">
        <Layers className="w-3.5 h-3.5 text-gray-400" />
        <select
          value={depth}
          onChange={(e) => onDepthChange(Number(e.target.value))}
          className="text-xs border border-gray-200 rounded-md px-1.5 py-1 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-400"
          title="Traversal depth"
        >
          <option value={1}>Depth 1</option>
          <option value={2}>Depth 2</option>
          <option value={3}>Depth 3</option>
          <option value={4}>Depth 4</option>
        </select>
      </div>

      {/* Layout toggle */}
      <button
        onClick={() =>
          onLayoutChange(layout === 'forceDirected' ? 'd3Force' : 'forceDirected')
        }
        className={`p-1.5 rounded-lg hover:bg-gray-100 transition-colors ${
          layout === 'd3Force' ? 'text-indigo-600 bg-indigo-50' : 'text-gray-500'
        }`}
        title={`Layout: ${layout === 'forceDirected' ? 'Force Directed' : 'D3 Force'} — click to toggle`}
      >
        <GitBranch className="w-4 h-4" />
      </button>

      {/* Zoom / fit reset */}
      <button
        onClick={onZoomReset}
        className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors"
        title="Fit graph to view"
      >
        <RotateCcw className="w-4 h-4" />
      </button>
    </div>
  );
}
