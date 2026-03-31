'use client';

import React, { useState } from 'react';
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

/** Format a snake_case tool name into title case. */
function formatToolName(name: string): string {
  return name
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function StatusIcon({ status }: { status: 'running' | 'success' | 'error' }) {
  switch (status) {
    case 'running':
      return <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />;
    case 'success':
      return <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />;
    case 'error':
      return <XCircle className="w-3.5 h-3.5 text-red-500" />;
  }
}

// =============================================================================
// Live Streaming Panel (expanded, shows real-time progress)
// =============================================================================

interface LiveReasoningPanelProps {
  tools: ToolStatus[];
}

export function LiveReasoningPanel({ tools }: LiveReasoningPanelProps) {
  if (!tools || tools.length === 0) return null;

  const runningCount = tools.filter((t) => t.status === 'running').length;
  const doneCount = tools.filter((t) => t.status !== 'running').length;

  return (
    <div className="flex justify-start animate-in slide-in-from-bottom-2 duration-300">
      <div className="max-w-[85%] w-full">
        {/* Header */}
        <div className="flex items-center gap-2 mb-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center border border-blue-200">
            <Search className="w-3.5 h-3.5 text-blue-600" />
          </div>
          <span className="text-sm font-medium text-gray-600">
            {runningCount > 0
              ? `Analyzing with ${tools.length} tool${tools.length !== 1 ? 's' : ''}…`
              : `Used ${doneCount} tool${doneCount !== 1 ? 's' : ''}`}
          </span>
        </div>

        {/* Tool list — always expanded during streaming */}
        <div className="ml-9 space-y-1.5">
          {tools.map((tool, idx) => (
            <div
              key={`${tool.name}-${idx}`}
              className={`flex items-start gap-2.5 px-3 py-2 rounded-lg border text-sm transition-all duration-300 animate-in slide-in-from-left-2 ${
                tool.status === 'running'
                  ? 'bg-blue-50/60 border-blue-100'
                  : tool.status === 'success'
                    ? 'bg-green-50/40 border-green-100'
                    : 'bg-red-50/40 border-red-100'
              }`}
            >
              <div className="flex-shrink-0 mt-0.5">
                <StatusIcon status={tool.status} />
              </div>
              <div className="flex flex-col min-w-0">
                <span className="font-medium text-gray-700 leading-tight">
                  {formatToolName(tool.name)}
                </span>
                {tool.description && (
                  <span className="text-xs text-gray-500 mt-0.5 truncate">
                    {tool.description}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Committed Message Panel (collapsible, shows persisted tool details)
// =============================================================================

interface ReasoningPanelProps {
  toolDetails: ToolDetail[];
  /** Start collapsed (default true). */
  defaultCollapsed?: boolean;
}

export function ReasoningPanel({
  toolDetails,
  defaultCollapsed = true,
}: ReasoningPanelProps) {
  const [isExpanded, setIsExpanded] = useState(!defaultCollapsed);

  if (!toolDetails || toolDetails.length === 0) return null;

  const successCount = toolDetails.filter((t) => t.status === 'success').length;
  const errorCount = toolDetails.filter((t) => t.status === 'error').length;

  return (
    <div className="mt-3 pt-3 border-t border-gray-100">
      {/* Collapsible header */}
      <button
        type="button"
        onClick={() => setIsExpanded((prev) => !prev)}
        className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 transition-colors w-full text-left group"
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
          <span className="text-xs px-1.5 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-100">
            {errorCount} failed
          </span>
        )}
        {successCount > 0 && !isExpanded && (
          <span className="text-xs text-gray-400">
            — {toolDetails.map((t) => formatToolName(t.name)).join(', ')}
          </span>
        )}
      </button>

      {/* Expanded detail rows */}
      {isExpanded && (
        <div className="mt-2 ml-6 space-y-1.5 animate-in slide-in-from-top-1 duration-200">
          {toolDetails.map((tool, idx) => (
            <div
              key={`${tool.name}-${idx}`}
              className={`flex items-start gap-2 px-3 py-2 rounded-lg text-sm ${
                tool.status === 'success'
                  ? 'bg-gray-50 border border-gray-100'
                  : 'bg-red-50/50 border border-red-100'
              }`}
            >
              <div className="flex-shrink-0 mt-0.5">
                <StatusIcon status={tool.status} />
              </div>
              <div className="flex flex-col min-w-0">
                <span className="font-medium text-gray-700 leading-tight">
                  {formatToolName(tool.name)}
                </span>
                {tool.description && (
                  <span className="text-xs text-gray-500 mt-0.5">
                    &ldquo;{tool.description}&rdquo;
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
