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
        <Layers className="w-3.5 h-3.5 text-[var(--text-tertiary)]" />
        <select
          value={depth}
          onChange={(e) => onDepthChange(Number(e.target.value))}
          className="text-xs border border-[var(--border)] rounded-md px-1.5 py-1 bg-[var(--surface)] text-[var(--foreground)] focus:outline-none focus:ring-1 focus:ring-[var(--amber-3)]"
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
        className={`p-1.5 rounded-lg hover:bg-[var(--surface-elevated)] transition-colors ${
          layout === 'd3Force' ? 'text-[var(--amber-8)] bg-[var(--amber-2)]' : 'text-[var(--text-secondary)]'
        }`}
        title={`Layout: ${layout === 'forceDirected' ? 'Force Directed' : 'D3 Force'} — click to toggle`}
      >
        <GitBranch className="w-4 h-4" />
      </button>

      {/* Zoom / fit reset */}
      <button
        onClick={onZoomReset}
        className="p-1.5 rounded-lg hover:bg-[var(--surface-elevated)] text-[var(--text-secondary)] hover:text-[var(--foreground)] transition-colors"
        title="Fit graph to view"
      >
        <RotateCcw className="w-4 h-4" />
      </button>
    </div>
  );
}
