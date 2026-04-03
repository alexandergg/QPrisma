'use client';

import React, { memo } from 'react';
import { Play, Mic, Eye, Tag } from 'lucide-react';
import { formatTime } from '@/lib/utils';

interface TimestampBadgeProps {
  timestamp: number;
  type?: 'visual' | 'audio' | 'entity';
  label?: string;
  onClick?: () => void;
  size?: 'sm' | 'md';
  score?: number;
}

function TimestampBadge({
  timestamp,
  type = 'visual',
  label,
  onClick,
  size = 'sm',
  score,
}: TimestampBadgeProps) {
  const iconMap = {
    visual: Eye,
    audio: Mic,
    entity: Tag,
  };

  const colorMap = {
    visual: {
      bg: 'bg-[var(--blue-3)] hover:bg-[var(--blue-3)]/80',
      text: 'text-[var(--blue-8)]',
      icon: 'text-[var(--blue-7)]',
    },
    audio: {
      bg: 'bg-[var(--sage-2)] hover:bg-[var(--sage-3)]',
      text: 'text-[var(--sage-8)]',
      icon: 'text-[var(--sage-7)]',
    },
    entity: {
      bg: 'bg-[var(--amber-2)] hover:bg-[var(--amber-3)]',
      text: 'text-[var(--amber-8)]',
      icon: 'text-[var(--amber-7)]',
    },
  };

  const confidenceRing = score !== undefined
    ? score >= 0.8 ? 'ring-1 ring-[var(--sage-7)]/30'
    : score >= 0.5 ? 'ring-1 ring-[var(--amber-6)]/30'
    : 'ring-1 ring-[var(--rose-7)]/30'
    : '';

  const Icon = iconMap[type];
  const colors = colorMap[type];

  const sizeClasses = {
    sm: {
      wrapper: 'px-2 py-1 gap-1.5',
      icon: 'w-3 h-3',
      text: 'text-xs',
    },
    md: {
      wrapper: 'px-3 py-1.5 gap-2',
      icon: 'w-4 h-4',
      text: 'text-sm',
    },
  };

  const sizes = sizeClasses[size];

  return (
    <button
      onClick={onClick}
      className={`
        inline-flex items-center rounded-full font-medium transition-all
        ${colors.bg} ${sizes.wrapper} ${confidenceRing}
        group cursor-pointer
      `}
    >
      <Play className={`${sizes.icon} ${colors.icon} fill-current`} />
      <span className={`${sizes.text} ${colors.text} font-mono`}>
        {formatTime(timestamp)}
      </span>
      {label && (
        <span className={`${sizes.text} text-[var(--text-secondary)] font-normal`}>
          {label}
        </span>
      )}
      <Icon className={`${sizes.icon} ${colors.icon} opacity-60`} />
    </button>
  );
}

export default memo(TimestampBadge);
