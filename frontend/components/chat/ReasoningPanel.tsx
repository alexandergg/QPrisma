'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronRight,
  Search,
  CheckCircle2,
  XCircle,
  Loader2,
  Wrench,
} from 'lucide-react';
import type { ToolStatus } from './MessageBubble';
import type { ToolDetail } from '@/hooks/useChatState';

// =============================================================================
// Helpers
// =============================================================================

function formatToolName(name: string): string {
  return name
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function StatusIcon({ status }: { status: 'running' | 'success' | 'error' }) {
  switch (status) {
    case 'running':
      return <Loader2 className="w-3.5 h-3.5 text-[var(--violet-8)] animate-spin" />;
    case 'success':
      return <CheckCircle2 className="w-3.5 h-3.5 text-[var(--sage-7)]" />;
    case 'error':
      return <XCircle className="w-3.5 h-3.5 text-[var(--rose-7)]" />;
  }
}

// =============================================================================
// Live Streaming Panel
// =============================================================================

interface LiveReasoningPanelProps {
  tools: ToolStatus[];
}

export function LiveReasoningPanel({ tools }: LiveReasoningPanelProps) {
  if (!tools || tools.length === 0) return null;

  const runningCount = tools.filter((t) => t.status === 'running').length;
  const doneCount = tools.filter((t) => t.status !== 'running').length;

  return (
    <div className="flex items-start gap-3">
      {/* Avatar */}
      <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-gradient-to-br from-violet-500 to-violet-600 flex items-center justify-center shadow-lg shadow-violet-500/20 mt-0.5">
        <Search className="w-4 h-4 text-white" />
      </div>

      <div className="flex-1 min-w-0 pt-0.5">
        <p className="text-sm font-medium text-[var(--text-secondary)] mb-2">
          {runningCount > 0
            ? `Analyzing with ${tools.length} tool${tools.length !== 1 ? 's' : ''}…`
            : `Used ${doneCount} tool${doneCount !== 1 ? 's' : ''}`}
        </p>

        <div className="space-y-1.5">
          <AnimatePresence initial={false}>
            {tools.map((tool, idx) => (
              <motion.div
                key={`${tool.name}-${idx}`}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, delay: idx * 0.05 }}
                className={`flex items-start gap-2.5 px-3 py-2 rounded-lg border text-sm transition-colors duration-300 ${
                  tool.status === 'running'
                    ? 'bg-[var(--violet-2)] border-[var(--violet-5)] tool-running-shimmer'
                    : tool.status === 'success'
                      ? 'bg-[var(--sage-2)] border-[var(--sage-3)]'
                      : 'bg-[var(--rose-3)]/30 border-[var(--rose-3)]'
                }`}
              >
                <div className="flex-shrink-0 mt-0.5">
                  <StatusIcon status={tool.status} />
                </div>
                <div className="flex flex-col min-w-0">
                  <span className="font-medium text-[var(--foreground)] leading-tight">
                    {formatToolName(tool.name)}
                  </span>
                  {tool.description && (
                    <span className="text-xs text-[var(--text-tertiary)] mt-0.5 truncate">
                      {tool.description}
                    </span>
                  )}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Committed Reasoning Panel (collapsible accordion)
// =============================================================================

interface ReasoningPanelProps {
  toolDetails: ToolDetail[];
  defaultCollapsed?: boolean;
}

export function ReasoningPanel({
  toolDetails,
  defaultCollapsed = true,
}: ReasoningPanelProps) {
  const [isExpanded, setIsExpanded] = useState(!defaultCollapsed);

  if (!toolDetails || toolDetails.length === 0) return null;

  const errorCount = toolDetails.filter((t) => t.status === 'error').length;

  return (
    <div className="mt-4 pt-3 border-t border-[var(--border-subtle)]">
      <button
        type="button"
        onClick={() => setIsExpanded((prev) => !prev)}
        className="flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--foreground)] transition-colors w-full text-left"
      >
        <ChevronRight
          className={`w-4 h-4 transition-transform duration-200 ${
            isExpanded ? 'rotate-90' : ''
          }`}
        />
        <Wrench className="w-3.5 h-3.5" />
        <span className="font-medium">
          Used {toolDetails.length} tool{toolDetails.length !== 1 ? 's' : ''}
        </span>
        {errorCount > 0 && (
          <span className="text-xs px-1.5 py-0.5 rounded-full bg-[var(--rose-3)] text-[var(--rose-8)] border border-[var(--rose-3)]">
            {errorCount} failed
          </span>
        )}
        {!isExpanded && (
          <span className="text-xs text-[var(--text-tertiary)] truncate">
            — {toolDetails.map((t) => formatToolName(t.name)).join(', ')}
          </span>
        )}
      </button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 ml-6 space-y-1.5">
              {toolDetails.map((tool, idx) => (
                <div
                  key={`${tool.name}-${idx}`}
                  className={`flex items-start gap-2 px-3 py-2 rounded-lg text-sm ${
                    tool.status === 'success'
                      ? 'bg-[var(--surface-elevated)] border border-[var(--border-subtle)]'
                      : 'bg-[var(--rose-3)]/30 border border-[var(--rose-3)]'
                  }`}
                >
                  <div className="flex-shrink-0 mt-0.5">
                    <StatusIcon status={tool.status} />
                  </div>
                  <div className="flex flex-col min-w-0">
                    <span className="font-medium text-[var(--foreground)] leading-tight">
                      {formatToolName(tool.name)}
                    </span>
                    {tool.description && (
                      <span className="text-xs text-[var(--text-tertiary)] mt-0.5">
                        &ldquo;{tool.description}&rdquo;
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
