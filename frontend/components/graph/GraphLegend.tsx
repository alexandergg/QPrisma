'use client';

import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

// ============================================================================
// Legend data — mirrors _NODE_VISUAL_MAP from backend
// ============================================================================

const LEGEND_ITEMS: { label: string; color: string }[] = [
  { label: 'Video', color: '#B8882A' },
  { label: 'Chapter', color: '#86611C' },
  { label: 'Scene', color: '#E5BD56' },
  { label: 'Frame', color: '#5C94F0' },
  { label: 'Entity', color: '#72A872' },
  { label: 'Audio', color: '#5E905E' },
  { label: 'Topic', color: '#EFD07A' },
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
      className={`bg-[var(--surface)]/90 backdrop-blur rounded-lg shadow-[var(--shadow-sm)] border border-[var(--border)] text-xs select-none ${className}`}
    >
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex items-center gap-1 px-2 py-1.5 w-full text-left text-[var(--text-secondary)] hover:text-[var(--foreground)]"
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
              <span className="text-[var(--text-secondary)]">{item.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
