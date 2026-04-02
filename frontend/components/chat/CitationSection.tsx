'use client';

import React, { memo, useState, useMemo } from 'react';
import { ChevronDown, ChevronUp, Bookmark } from 'lucide-react';
import CitationCard from './CitationCard';
import type { ChatMessageSource } from './MessageBubble';

const DEFAULT_VISIBLE = 5;

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

  const groupedSources = useMemo(() => {
    const sorted = [...sources].sort((a, b) => (b.score || 0) - (a.score || 0));
    return sorted.reduce<Record<string, ChatMessageSource[]>>((acc, source) => {
      const key = source.videoTitle || source.videoId || 'Current video';
      if (!acc[key]) acc[key] = [];
      acc[key].push(source);
      return acc;
    }, {});
  }, [sources]);

  const totalSources = sources.length;
  const confidence = confidenceLabel(sources);

  return (
    <div className="mt-3 pt-3 border-t border-gray-100">
      {/* Header */}
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-1.5">
          <Bookmark className="w-3.5 h-3.5 text-gray-400" />
          <span className="text-xs font-medium text-gray-500">
            Sources
          </span>
          <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded-full font-medium">
            {totalSources}
          </span>
        </div>
        <span className="text-[11px] text-gray-400 font-medium">
          {confidence}
        </span>
      </div>

      {/* Grouped citation cards */}
      <div className="space-y-3">
        {Object.entries(groupedSources).slice(0, 3).map(([groupLabel, groupSources]) => {
          const visibleSources = expanded ? groupSources : groupSources.slice(0, DEFAULT_VISIBLE);
          const hiddenCount = groupSources.length - DEFAULT_VISIBLE;

          return (
            <div key={groupLabel}>
              {/* Group label (shown when multiple groups) */}
              {Object.keys(groupedSources).length > 1 && (
                <p className="text-[11px] text-gray-400 font-medium mb-1.5 flex items-center gap-1">
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

              {/* Expand/collapse toggle */}
              {hiddenCount > 0 && (
                <button
                  onClick={() => setExpanded(!expanded)}
                  className="flex items-center gap-1 mt-2 text-xs text-gray-400 hover:text-gray-600 transition-colors"
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
        })}
      </div>
    </div>
  );
}

export default memo(CitationSection);
