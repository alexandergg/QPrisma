'use client';

import React, { memo } from 'react';
import { motion } from 'framer-motion';
import {
  CalendarDays,
  CheckCircle,
  Clock,
  Eye,
  Film,
  HardDrive,
  Loader2,
  MoreVertical,
  Play,
  Trash2,
} from 'lucide-react';
import { formatTime, formatFileSize, formatDate } from '@/lib/utils';

interface VideoCardProps {
  id: string;
  name: string;
  duration?: number;
  size?: number;
  uploadedAt: Date;
  isProcessed: boolean;
  isProcessing?: boolean;
  framesAnalyzed?: number;
  onSelect?: () => void;
  onDelete?: () => void;
  isSelected?: boolean;
}

function VideoCard({
  name,
  duration,
  size,
  uploadedAt,
  isProcessed,
  isProcessing = false,
  framesAnalyzed,
  onSelect,
  onDelete,
  isSelected = false,
}: VideoCardProps) {
  const [showMenu, setShowMenu] = React.useState(false);
  const statusLabel = isProcessed ? 'Ready' : isProcessing ? 'Processing' : 'Pending';
  const StatusIcon = isProcessed ? CheckCircle : isProcessing ? Loader2 : Clock;
  const statusClassName = isProcessed
    ? 'bg-[var(--sage-3)] text-[var(--sage-8)]'
    : isProcessing
      ? 'bg-[var(--violet-3)] text-[var(--violet-11)]'
      : 'bg-[var(--surface-elevated)] text-[var(--text-secondary)]';
  const summaryLabel = isProcessed
    ? 'Ready for analysis'
    : isProcessing
      ? 'Analyzing video'
      : 'Awaiting processing';

  return (
    <motion.div
      whileHover={{ y: -4, transition: { duration: 0.2, ease: [0.34, 1.56, 0.64, 1] } }}
      onClick={onSelect}
      className={`
        group relative bg-[var(--surface)] rounded-2xl overflow-hidden cursor-pointer
        border-2 transition-[border-color,box-shadow] duration-200
        shadow-lg shadow-gray-200/50 hover:shadow-xl hover:shadow-violet-200/30
        ${isSelected ? 'border-violet-500 ring-4 ring-violet-100' : 'border-transparent hover:border-violet-200'}
      `}
    >
      <div className="relative overflow-hidden border-b border-[var(--border-subtle)] bg-gradient-to-br from-[var(--violet-1)] via-white to-[var(--sage-2)] p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/85 text-[var(--violet-8)] shadow-sm ring-1 ring-[var(--violet-3)]">
            <Film className="h-7 w-7" aria-hidden="true" />
          </div>
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${statusClassName}`}>
            <StatusIcon className={`h-3.5 w-3.5 ${isProcessing ? 'animate-spin' : ''}`} aria-hidden="true" />
            {statusLabel}
          </span>
        </div>

        <div className="mt-6 flex items-end justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
              Video file
            </p>
            <p className="mt-1 text-sm font-semibold text-[var(--foreground)]">
              {summaryLabel}
            </p>
          </div>
          {duration !== undefined && (
            <span className="rounded-[var(--radius-md)] bg-[var(--foreground)]/75 px-2 py-1 font-mono text-xs text-white">
              {formatTime(duration)}
            </span>
          )}
        </div>

        {isProcessing && (
          <div className="mt-4 flex items-center gap-2 rounded-xl bg-white/85 px-3 py-2 text-sm font-medium text-[var(--violet-9)] shadow-sm">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            <span>Processing...</span>
          </div>
        )}

        {isSelected && (
          <div className="absolute top-2 left-2 bg-violet-500 text-white p-1.5 rounded-lg shadow-lg">
            <CheckCircle className="w-4 h-4" aria-hidden="true" />
          </div>
        )}
      </div>

      {/* Info */}
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-gray-900 truncate group-hover:text-violet-600 transition-colors">
              {name}
            </h3>
          </div>

          {/* Menu button */}
          <div className="relative">
            <button
              onClick={(e) => {
                e.stopPropagation();
                setShowMenu(!showMenu);
              }}
              className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-colors opacity-0 group-hover:opacity-100"
              aria-label="Video options"
              aria-haspopup="true"
              aria-expanded={showMenu}
            >
              <MoreVertical className="w-4 h-4" />
            </button>

            {/* Dropdown menu */}
            {showMenu && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowMenu(false);
                  }}
                />
                <div role="menu" className="absolute right-0 top-8 z-20 bg-white rounded-xl shadow-xl border border-gray-100 py-1 min-w-[140px]">
                  {onDelete && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setShowMenu(false);
                        onDelete();
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
                      role="menuitem"
                    >
                      <Trash2 className="w-4 h-4" />
                      Delete
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-[var(--text-secondary)]">
          {size !== undefined && (
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--surface-elevated)] px-2.5 py-1.5">
              <HardDrive className="h-3.5 w-3.5" aria-hidden="true" />
              {formatFileSize(size)}
            </span>
          )}
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--surface-elevated)] px-2.5 py-1.5">
            <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
            {formatDate(uploadedAt)}
          </span>
          {framesAnalyzed !== undefined && (
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--surface-elevated)] px-2.5 py-1.5">
              <Eye className="h-3.5 w-3.5" aria-hidden="true" />
              {framesAnalyzed} frames
            </span>
          )}
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--surface-elevated)] px-2.5 py-1.5">
            <Play className="h-3.5 w-3.5" aria-hidden="true" />
            Select
          </span>
        </div>
      </div>
    </motion.div>
  );
}

export default memo(VideoCard);
