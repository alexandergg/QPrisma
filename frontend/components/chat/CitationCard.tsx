'use client';

import React, { memo } from 'react';
import { Play, Eye, Mic, Tag } from 'lucide-react';
import { formatTime } from '@/lib/utils';

export interface CitationCardProps {
  timestamp: number;
  type: 'visual' | 'audio' | 'entity';
  description?: string;
  score?: number;
  onClick?: () => void;
}

const typeConfig = {
  visual: {
    icon: Eye,
    label: 'Visual',
    border: 'border-l-indigo-400',
    bg: 'bg-indigo-50/60 hover:bg-indigo-50',
    iconColor: 'text-indigo-500',
    labelColor: 'text-indigo-600',
    dotFilled: 'bg-indigo-400',
    dotEmpty: 'bg-indigo-200',
  },
  audio: {
    icon: Mic,
    label: 'Audio',
    border: 'border-l-emerald-400',
    bg: 'bg-emerald-50/60 hover:bg-emerald-50',
    iconColor: 'text-emerald-500',
    labelColor: 'text-emerald-600',
    dotFilled: 'bg-emerald-400',
    dotEmpty: 'bg-emerald-200',
  },
  entity: {
    icon: Tag,
    label: 'Entity',
    border: 'border-l-amber-400',
    bg: 'bg-amber-50/60 hover:bg-amber-50',
    iconColor: 'text-amber-500',
    labelColor: 'text-amber-600',
    dotFilled: 'bg-amber-400',
    dotEmpty: 'bg-amber-200',
  },
};

function ConfidenceDots({ score, filledClass, emptyClass }: { score: number; filledClass: string; emptyClass: string }) {
  const filled = Math.max(1, Math.min(5, Math.round(score * 5)));
  return (
    <div className="flex items-center gap-0.5" title={`${Math.round(score * 100)}% confidence`}>
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${i < filled ? filledClass : emptyClass}`}
        />
      ))}
    </div>
  );
}

function CitationCard({ timestamp, type, description, score, onClick }: CitationCardProps) {
  const config = typeConfig[type];
  const Icon = config.icon;

  return (
    <button
      onClick={onClick}
      className={`
        w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border-l-3
        ${config.border} ${config.bg}
        transition-all duration-200 cursor-pointer group
        hover:shadow-sm
        text-left
      `}
    >
      {/* Type icon + label */}
      <div className="flex items-center gap-1.5 flex-shrink-0 min-w-[68px]">
        <Icon className={`w-3.5 h-3.5 ${config.iconColor}`} />
        <span className={`text-xs font-medium ${config.labelColor}`}>{config.label}</span>
      </div>

      {/* Timestamp */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <Play className={`w-3 h-3 ${config.iconColor} fill-current opacity-70 group-hover:opacity-100 transition-opacity`} />
        <span className={`text-xs font-mono font-semibold ${config.labelColor}`}>
          {formatTime(timestamp)}
        </span>
      </div>

      {/* Description */}
      {description && (
        <span className="text-xs text-gray-500 truncate flex-1 min-w-0">
          {description}
        </span>
      )}

      {/* Confidence dots */}
      {typeof score === 'number' && score > 0 && (
        <div className="flex-shrink-0 ml-auto">
          <ConfidenceDots score={score} filledClass={config.dotFilled} emptyClass={config.dotEmpty} />
        </div>
      )}
    </button>
  );
}

export default memo(CitationCard);
