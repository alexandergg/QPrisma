'use client';

import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

// ============================================================================
// Legend data — mirrors _NODE_VISUAL_MAP from backend
// ============================================================================

const LEGEND_ITEMS: { label: string; color: string }[] = [
  { label: 'Video', color: '#4F46E5' },
  { label: 'Chapter', color: '#7C3AED' },
  { label: 'Scene', color: '#6366F1' },
  { label: 'Frame', color: '#06B6D4' },
  { label: 'Entity', color: '#8B5CF6' },
  { label: 'Audio', color: '#10B981' },
  { label: 'Topic', color: '#F59E0B' },
];

// ============================================================================
// Component
// ============================================================================

interface GraphLegendProps {
  className?: string;
}

export function GraphLegend({ className = '' }: GraphLegendProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div
      className={`bg-white/90 backdrop-blur rounded-lg shadow border border-gray-200 text-xs select-none ${className}`}
    >
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex items-center gap-1 px-2 py-1.5 w-full text-left text-gray-500 hover:text-gray-700"
      >
        <span className="font-medium">Legend</span>
        {collapsed ? (
          <ChevronDown className="w-3 h-3 ml-auto" />
        ) : (
          <ChevronUp className="w-3 h-3 ml-auto" />
        )}
      </button>

      {!collapsed && (
        <div className="px-2 pb-2 grid grid-cols-2 gap-x-3 gap-y-1">
          {LEGEND_ITEMS.map((item) => (
            <div key={item.label} className="flex items-center gap-1.5">
              <span
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{ backgroundColor: item.color }}
              />
              <span className="text-gray-600">{item.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
