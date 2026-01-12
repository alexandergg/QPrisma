'use client';

import React from 'react';
import { Play, Mic, Eye, Tag } from 'lucide-react';

interface TimestampBadgeProps {
  timestamp: number;
  type?: 'visual' | 'audio' | 'entity';
  label?: string;
  onClick?: () => void;
  size?: 'sm' | 'md';
}

function formatTime(seconds: number): string {
  if (!seconds || isNaN(seconds)) return '0:00';
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  
  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export default function TimestampBadge({
  timestamp,
  type = 'visual',
  label,
  onClick,
  size = 'sm',
}: TimestampBadgeProps) {
  const iconMap = {
    visual: Eye,
    audio: Mic,
    entity: Tag,
  };

  const colorMap = {
    visual: {
      bg: 'bg-indigo-50 hover:bg-indigo-100',
      text: 'text-indigo-600',
      icon: 'text-indigo-500',
    },
    audio: {
      bg: 'bg-emerald-50 hover:bg-emerald-100',
      text: 'text-emerald-600',
      icon: 'text-emerald-500',
    },
    entity: {
      bg: 'bg-amber-50 hover:bg-amber-100',
      text: 'text-amber-600',
      icon: 'text-amber-500',
    },
  };

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
        ${colors.bg} ${sizes.wrapper}
        group cursor-pointer
      `}
    >
      <Play className={`${sizes.icon} ${colors.icon} fill-current`} />
      <span className={`${sizes.text} ${colors.text} font-mono`}>
        {formatTime(timestamp)}
      </span>
      {label && (
        <span className={`${sizes.text} text-gray-500 font-normal`}>
          {label}
        </span>
      )}
      <Icon className={`${sizes.icon} ${colors.icon} opacity-60`} />
    </button>
  );
}
