'use client';

import React, { memo, useState, useMemo, useCallback } from 'react';
import { ChevronDown, ChevronUp, Bookmark } from 'lucide-react';
import CitationCard from './CitationCard';
import type { ChatMessageSource } from './MessageBubble';

const DEFAULT_VISIBLE = 5;
const DEFAULT_GROUPS_VISIBLE = 3;

function confidenceLabel(sources: ChatMessageSource[]): string {
  const scored = sources.filter((s) => typeof s.score === 'number');
  if (scored.length === 0) return 'Evidence available';
  const avg = scored.reduce((sum, s) => sum + (s.score || 0), 0) / scored.length;
  if (avg >= 0.8) return 'High confidence';
  if (avg >= 0.5) return 'Medium confidence';
  return 'Low confidence';
}

interface CitationSectionProps {
  sources: ChatMessageSource[];
  onTimestampClick?: (timestamp: number) => void;
}

function CitationSection({ sources, onTimestampClick }: CitationSectionProps) {
  const [expanded, setExpanded] = useState(false);
  const [groupsExpanded, setGroupsExpanded] = useState(false);

  const groupedSources = useMemo(() => {
    const sorted = [...sources].sort((a, b) => (b.score || 0) - (a.score || 0));
    return sorted.reduce<Record<string, ChatMessageSource[]>>((acc, source) => {
      const key = source.videoTitle || source.videoId || 'Current video';
      if (!acc[key]) acc[key] = [];
      acc[key].push(source);
      return acc;
    }, {});
  }, [sources]);

  const groupEntries = useMemo(
    () => Object.entries(groupedSources),
    [groupedSources],
  );

  const hiddenGroupCount = groupEntries.length - DEFAULT_GROUPS_VISIBLE;

  const toggleGroupsExpanded = useCallback(() => {
    setGroupsExpanded((prev) => !prev);
  }, []);

  const totalSources = sources.length;
  const confidence = confidenceLabel(sources);

  const totalGroups = groupEntries.length;

  const renderGroup = ([groupLabel, groupSources]: [string, ChatMessageSource[]]) => {
    const visibleSources = expanded ? groupSources : groupSources.slice(0, DEFAULT_VISIBLE);
    const hiddenCount = groupSources.length - DEFAULT_VISIBLE;

    return (
      <div key={groupLabel}>
        {/* Group label (shown when multiple groups) */}
        {totalGroups > 1 && (
          <p className="text-[11px] text-[var(--text-tertiary)] font-medium mb-1.5 flex items-center gap-1">
            <span className="truncate">{groupLabel}</span>
          </p>
        )}

        {/* Citation cards */}
        <div className="space-y-1.5">
          {visibleSources.map((source, idx) => (
            <CitationCard
              key={`${groupLabel}-${idx}-${source.timestamp}`}
              timestamp={source.timestamp}
              type={source.type}
              description={source.description}
              score={source.score}
              onClick={() => onTimestampClick?.(source.timestamp)}
            />
          ))}
        </div>

        {/* Expand/collapse toggle for citations within a group */}
        {hiddenCount > 0 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 mt-2 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
          >
            {expanded ? (
              <>
                <ChevronUp className="w-3.5 h-3.5" />
                Show less
              </>
            ) : (
              <>
                <ChevronDown className="w-3.5 h-3.5" />
                Show {hiddenCount} more reference{hiddenCount > 1 ? 's' : ''}
              </>
            )}
          </button>
        )}
      </div>
    );
  };

  const alwaysVisibleGroups = groupEntries.slice(0, DEFAULT_GROUPS_VISIBLE);
  const collapsibleGroups = groupEntries.slice(DEFAULT_GROUPS_VISIBLE);

  return (
    <div className="mt-3 pt-3 border-t border-[var(--border-subtle)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-1.5">
          <Bookmark className="w-3.5 h-3.5 text-[var(--text-tertiary)]" />
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            Sources
          </span>
          <span className="text-[10px] px-1.5 py-0.5 bg-[var(--surface-elevated)] text-[var(--text-secondary)] rounded-full font-medium">
            {totalSources}
          </span>
        </div>
        <span className="text-[11px] text-[var(--text-tertiary)] font-medium">
          {confidence}
        </span>
      </div>

      {/* Grouped citation cards */}
      <div className="space-y-3">
        {alwaysVisibleGroups.map(renderGroup)}

        {/* Collapsible overflow groups */}
        {collapsibleGroups.length > 0 && (
          <>
            <div
              className="grid transition-[grid-template-rows] duration-300 ease-in-out"
              style={{ gridTemplateRows: groupsExpanded ? '1fr' : '0fr' }}
            >
              <div className="overflow-hidden">
                <div className="space-y-3">
                  {collapsibleGroups.map(renderGroup)}
                </div>
              </div>
            </div>

            <button
              onClick={toggleGroupsExpanded}
              className="flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
              aria-expanded={groupsExpanded}
              aria-label={
                groupsExpanded
                  ? 'Show fewer source groups'
                  : `Show ${hiddenGroupCount} more source${hiddenGroupCount > 1 ? 's' : ''}`
              }
            >
              {groupsExpanded ? (
                <>
                  <ChevronUp className="w-3.5 h-3.5" />
                  Show less
                </>
              ) : (
                <>
                  <ChevronDown className="w-3.5 h-3.5" />
                  Show {hiddenGroupCount} more source{hiddenGroupCount > 1 ? 's' : ''}
                </>
              )}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default memo(CitationSection);
