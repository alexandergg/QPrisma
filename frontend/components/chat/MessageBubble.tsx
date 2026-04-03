'use client';

import React, { memo, useMemo } from 'react';
import { Sparkles, Film, Loader2, CheckCircle2, XCircle, Wrench, Terminal, ArrowRightCircle, Copy, ThumbsUp, ThumbsDown } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import TimestampBadge from './TimestampBadge';
import CitationSection from './CitationSection';
import { ReasoningPanel } from './ReasoningPanel';
import type { ToolDetail } from '@/hooks/useChatState';

/** Match [HH:MM:SS], [MM:SS], or bare HH:MM:SS / MM:SS patterns in text. */
const TIMESTAMP_RE_PATTERN = /\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?/;
const TIMESTAMP_RE_TEST = new RegExp(TIMESTAMP_RE_PATTERN.source);

function parseTimestampToSeconds(ts: string): number {
  const parts = ts.split(':').map(Number);
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return parts[0] * 60 + parts[1];
}

/**
 * Split a text node into segments of plain text and clickable timestamp badges.
 * Returns an array of React nodes.
 */
function renderTextWithTimestamps(
  text: string,
  onClick?: (seconds: number) => void,
): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  const globalRe = new RegExp(TIMESTAMP_RE_PATTERN.source, 'g');

  for (const match of text.matchAll(globalRe)) {
    const full = match[0];
    const core = match[1]; // the HH:MM:SS or MM:SS part
    const start = match.index!;

    // Push preceding plain text
    if (start > lastIndex) nodes.push(text.slice(lastIndex, start));

    const seconds = parseTimestampToSeconds(core);
    nodes.push(
      <TimestampBadge
        key={`ts-${start}-${core}`}
        timestamp={seconds}
        type="visual"
        size="sm"
        onClick={onClick ? () => onClick(seconds) : undefined}
      />,
    );

    lastIndex = start + full.length;
  }

  // Push remaining text
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

export interface ToolStatus {
  name: string;
  status: 'running' | 'success' | 'error';
  /** Human-readable description of what the tool is doing (e.g. the search query). */
  description?: string;
}

export interface ChatMessageSource {
  timestamp: number;
  type: 'visual' | 'audio' | 'entity';
  description?: string;
  score?: number;
  videoId?: string;
  videoTitle?: string;
}

export interface ChatMessageData {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  sources?: ChatMessageSource[];
  isLoading?: boolean;
  videoName?: string;
  toolCalls?: number;
  toolDetails?: ToolDetail[];
  isError?: boolean;
}

export function ToolProgress({ tools }: { tools: ToolStatus[] }) {
  if (!tools || tools.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 mb-4 w-full">
      <div className="flex items-center gap-2 text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wider mb-1 px-1">
        <Terminal className="w-3 h-3" />
        Process Log
      </div>
      <div className="space-y-2">
        {tools.map((tool, idx) => (
          <div 
            key={idx} 
            className={`flex items-center gap-2.5 p-3 rounded-lg border text-sm transition-all duration-300 animate-in slide-in-from-left-2 ${
              tool.status === 'running' 
                ? 'bg-[var(--blue-3)]/50 border-[var(--blue-3)] text-[var(--blue-8)]' 
                : tool.status === 'success'
                ? 'bg-[var(--sage-2)]/50 border-[var(--sage-3)] text-[var(--sage-8)]'
                : 'bg-[var(--rose-3)]/50 border-[var(--rose-3)] text-[var(--rose-8)]'
            }`}
          >
            <div className={`flex-shrink-0 ${tool.status === 'running' ? 'animate-spin' : ''}`}>
              {tool.status === 'running' && <Loader2 className="w-4 h-4" />}
              {tool.status === 'success' && <CheckCircle2 className="w-4 h-4" />}
              {tool.status === 'error' && <XCircle className="w-4 h-4" />}
            </div>
            
            <div className="flex flex-col min-w-0">
              <span className="font-medium">
                {tool.name.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')}
              </span>
              {tool.description ? (
                <span className="text-xs opacity-80 truncate">
                  {tool.description}
                </span>
              ) : (
                <span className="text-xs opacity-80">
                  {tool.status === 'running' ? 'Executing...' : tool.status === 'success' ? 'Completed' : 'Failed'}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1">
      <div className="w-2 h-2 bg-[var(--amber-7)] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <div className="w-2 h-2 bg-[var(--amber-7)] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <div className="w-2 h-2 bg-[var(--amber-7)] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </div>
  );
}

export const MessageBubble = memo(function MessageBubble({
  message,
  onTimestampClick,
  onSuggestionClick,
  onRetryLast,
}: {
  message: ChatMessageData;
  onTimestampClick?: (timestamp: number) => void;
  onSuggestionClick?: (suggestion: string) => void;
  onRetryLast?: () => void;
}) {
  const isUser = message.role === 'user';
  
  // Parse content for suggestions
  let displayContent = message.content;
  let suggestions: string[] = [];
  
  // Primary: structured delimiter from system prompt
  const suggestionSplit = displayContent.split('---SUGGESTED_QUESTIONS---');
  if (suggestionSplit.length > 1) {
    displayContent = suggestionSplit[0].trim();
    const suggestionsText = suggestionSplit[1].trim();
    suggestions = suggestionsText
      .split('\n')
      .map(s => s.replace(/^\d+\.\s*/, '').replace(/^[-*•]\s*/, '').trim())
      .filter(s => s.length > 0 && s.includes('?'));
  }

  // Fallback: detect markdown-style follow-up sections at the end of content
  if (suggestions.length === 0 && !isUser) {
    const followUpPattern = /(?:\n\s*(?:\*\*)?(?:Suggested|Follow[- ]?up|Related)\s+(?:questions?|follow[- ]?ups?)(?:\*\*)?[:\s]*\n)([\s\S]+?)$/i;
    const match = displayContent.match(followUpPattern);
    if (match) {
      const lines = match[1]
        .split('\n')
        .map(s => s.replace(/^\d+\.\s*/, '').replace(/^[-*•]\s*/, '').replace(/\*\*/g, '').trim())
        .filter(s => s.length > 0 && s.includes('?'));
      if (lines.length >= 2) {
        suggestions = lines;
        displayContent = displayContent.slice(0, match.index).trim();
      }
    }
  }

  // Memoize custom ReactMarkdown components to render inline timestamp links
  const markdownComponents = useMemo(() => ({
    p: ({ children }: { children?: React.ReactNode }) => {
      const processed = React.Children.map(children, (child) => {
        if (typeof child === 'string' && TIMESTAMP_RE_TEST.test(child)) {
          return <>{renderTextWithTimestamps(child, onTimestampClick)}</>;
        }
        return child;
      });
      return <p>{processed}</p>;
    },
    li: ({ children }: { children?: React.ReactNode }) => {
      const processed = React.Children.map(children, (child) => {
        if (typeof child === 'string' && TIMESTAMP_RE_TEST.test(child)) {
          return <>{renderTextWithTimestamps(child, onTimestampClick)}</>;
        }
        return child;
      });
      return <li>{processed}</li>;
    },
    strong: ({ children }: { children?: React.ReactNode }) => {
      const processed = React.Children.map(children, (child) => {
        if (typeof child === 'string' && TIMESTAMP_RE_TEST.test(child)) {
          return <>{renderTextWithTimestamps(child, onTimestampClick)}</>;
        }
        return child;
      });
      return <strong>{processed}</strong>;
    },
  }), [onTimestampClick]);

  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-in slide-in-from-bottom-2 duration-300 group`}
    >
      <div className={`max-w-[85%] ${isUser ? '' : ''}`}>
        {/* Assistant avatar and label */}
        {!isUser && (
          <div className="flex items-center gap-2 mb-2">
            <div className="w-7 h-7 rounded-lg bg-[var(--amber-8)] flex items-center justify-center shadow-[var(--shadow-sm)]">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <span className="text-sm font-medium text-[var(--text-secondary)]">QPrisma</span>
          </div>
        )}

        {/* Message bubble */}
        <div
          className={`p-4 rounded-2xl ${
            isUser
              ? 'bg-[var(--foreground)] text-[var(--surface)] rounded-tr-md shadow-[var(--shadow-md)]'
              : 'bg-[var(--surface)] text-[var(--foreground)] rounded-tl-md shadow-[var(--shadow-xs)] border border-[var(--border-subtle)]'
          }`}
        >
          {message.isLoading ? (
            <div className="flex items-center gap-3 py-1">
              <TypingIndicator />
              <span className="text-sm text-[var(--text-secondary)]">Analyzing...</span>
            </div>
          ) : (
            <>
              {/* Video reference for user messages */}
              {isUser && message.videoName && (
                <div className="flex items-center gap-1.5 text-white/80 text-xs mb-2">
                  <Film className="w-3 h-3" />
                  {message.videoName}
                </div>
              )}

              {/* Message content with Markdown rendering */}
              {isUser ? (
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
              ) : (
                <div className="text-sm leading-relaxed prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-strong:text-[var(--foreground)] prose-code:text-[var(--amber-11)] prose-code:bg-[var(--amber-2)] prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none">
                  <ReactMarkdown components={markdownComponents}>{displayContent}</ReactMarkdown>
                </div>
              )}

              {/* Agent Reasoning Panel — collapsible tool call details */}
              {!isUser && message.toolDetails && message.toolDetails.length > 0 && (
                <ReasoningPanel toolDetails={message.toolDetails} />
              )}

              {/* Suggestions Chips */}
              {!isUser && suggestions.length > 0 && (
                <div className="mt-4 pt-3 border-t border-[var(--border-subtle)] flex flex-col gap-2">
                  <p className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wide">Suggested Follow-ups</p>
                  <div className="flex flex-wrap gap-2">
                    {suggestions.map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => onSuggestionClick?.(suggestion)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--amber-2)] text-[var(--amber-11)] hover:bg-[var(--amber-3)] rounded-full text-sm transition-colors border border-[var(--amber-3)] text-left"
                      >
                        <span className="flex-1">{suggestion}</span>
                        <ArrowRightCircle className="w-4 h-4 opacity-50" />
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Sources / Citation Cards */}
              {!isUser && message.sources && message.sources.length > 0 && (
                <CitationSection
                  sources={message.sources}
                  onTimestampClick={onTimestampClick}
                />
              )}

              {!isUser && message.isError && onRetryLast && (
                <div className="mt-3 pt-3 border-t border-[var(--border-subtle)]">
                  <button
                    onClick={onRetryLast}
                    className="text-sm px-3 py-1.5 rounded-lg bg-[var(--rose-3)] text-[var(--rose-8)] hover:bg-[var(--rose-3)]/80 transition-colors"
                  >
                    Retry last prompt
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Message Actions Bar */}
        {!isUser && !message.isLoading && (
          <div className="flex items-center gap-1 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <button className="p-1.5 hover:bg-[var(--surface-elevated)] rounded-[var(--radius-sm)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors" title="Copy">
              <Copy className="w-3.5 h-3.5" />
            </button>
            <button className="p-1.5 hover:bg-[var(--surface-elevated)] rounded-[var(--radius-sm)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors" title="Good response">
              <ThumbsUp className="w-3.5 h-3.5" />
            </button>
            <button className="p-1.5 hover:bg-[var(--surface-elevated)] rounded-[var(--radius-sm)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors" title="Bad response">
              <ThumbsDown className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
});
