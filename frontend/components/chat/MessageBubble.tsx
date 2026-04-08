'use client';

import React, { memo, useMemo, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Sparkles,
  Film,
  ArrowRight,
  Check,
  Copy,
  RefreshCw,
} from 'lucide-react';
import { messageBubble } from '@/lib/animations';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import TimestampBadge from './TimestampBadge';
import CitationSection from './CitationSection';
import { ReasoningPanel } from './ReasoningPanel';
import CodeBlock from './CodeBlock';
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

// ---------------------------------------------------------------------------
// Inline sub-components
// ---------------------------------------------------------------------------

function MessageActions({
  content,
  onRetry,
  isError,
}: {
  content: string;
  onRetry?: () => void;
  isError?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  }, [content]);

  return (
    <div className="flex items-center gap-1 mt-3 opacity-0 group-hover/message:opacity-100 transition-opacity duration-200">
      <button
        onClick={handleCopy}
        className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition-colors"
        title={copied ? 'Copied!' : 'Copy message'}
        aria-label={copied ? 'Copied' : 'Copy message'}
      >
        {copied ? (
          <Check className="w-3.5 h-3.5 text-green-500" />
        ) : (
          <Copy className="w-3.5 h-3.5" />
        )}
      </button>
      {isError && onRetry && (
        <button
          onClick={onRetry}
          className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)] transition-colors"
          title="Retry"
          aria-label="Retry"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble
// ---------------------------------------------------------------------------

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
  const isStreaming = message.id === 'streaming';
  const isUser = message.role === 'user';

  // ── Suggestion parsing ───────────────────────────────────────────────────
  let displayContent = message.content;
  let suggestions: string[] = [];

  const suggestionSplit = displayContent.split('---SUGGESTED_QUESTIONS---');
  if (suggestionSplit.length > 1) {
    displayContent = suggestionSplit[0].trim();
    const suggestionsText = suggestionSplit[1].trim();
    suggestions = suggestionsText
      .split('\n')
      .map((s) =>
        s
          .replace(/^\d+\.\s*/, '')
          .replace(/^[-*•]\s*/, '')
          .trim(),
      )
      .filter((s) => s.length > 0 && s.includes('?'));
  }

  if (suggestions.length === 0 && !isUser) {
    const followUpPattern =
      /(?:\n\s*(?:\*\*)?(?:Suggested|Follow[- ]?up|Related)\s+(?:questions?|follow[- ]?ups?)(?:\*\*)?[:\s]*\n)([\s\S]+?)$/i;
    const match = displayContent.match(followUpPattern);
    if (match) {
      const lines = match[1]
        .split('\n')
        .map((s) =>
          s
            .replace(/^\d+\.\s*/, '')
            .replace(/^[-*•]\s*/, '')
            .replace(/\*\*/g, '')
            .trim(),
        )
        .filter((s) => s.length > 0 && s.includes('?'));
      if (lines.length >= 2) {
        suggestions = lines;
        displayContent = displayContent.slice(0, match.index).trim();
      }
    }
  }

  // ── Memoized Markdown components ─────────────────────────────────────────
  const markdownComponents = useMemo(
    () => ({
      // Code blocks → CodeBlock with syntax highlighting + copy
      pre({ children }: { children?: React.ReactNode }) {
        const codeChild = React.Children.toArray(children).find((child) =>
          React.isValidElement(child),
        );
        let language = '';
        if (React.isValidElement(codeChild)) {
          const cn =
            (codeChild.props as Record<string, string>).className || '';
          const m = /language-(\w+)/.exec(cn);
          if (m) language = m[1];
        }
        return <CodeBlock language={language}>{children}</CodeBlock>;
      },

      // Inline code
      code({
        children,
        className,
        ...props
      }: React.HTMLAttributes<HTMLElement> & { node?: unknown }) {
        if (className && /language-/.test(className)) {
          return (
            <code className={className} {...props}>
              {children}
            </code>
          );
        }
        return (
          <code
            className="px-1.5 py-0.5 bg-[var(--violet-3)] text-[var(--violet-9)] rounded-md font-mono text-[0.85em] font-medium"
            {...props}
          >
            {children}
          </code>
        );
      },

      // Timestamp-aware paragraphs
      p({ children }: { children?: React.ReactNode }) {
        const processed = React.Children.map(children, (child) => {
          if (typeof child === 'string' && TIMESTAMP_RE_TEST.test(child)) {
            return (
              <>{renderTextWithTimestamps(child, onTimestampClick)}</>
            );
          }
          return child;
        });
        return <p>{processed}</p>;
      },
      li({ children }: { children?: React.ReactNode }) {
        const processed = React.Children.map(children, (child) => {
          if (typeof child === 'string' && TIMESTAMP_RE_TEST.test(child)) {
            return (
              <>{renderTextWithTimestamps(child, onTimestampClick)}</>
            );
          }
          return child;
        });
        return <li>{processed}</li>;
      },
      strong({ children }: { children?: React.ReactNode }) {
        const processed = React.Children.map(children, (child) => {
          if (typeof child === 'string' && TIMESTAMP_RE_TEST.test(child)) {
            return (
              <>{renderTextWithTimestamps(child, onTimestampClick)}</>
            );
          }
          return child;
        });
        return <strong>{processed}</strong>;
      },

      // Styled blockquote
      blockquote({ children }: { children?: React.ReactNode }) {
        return (
          <blockquote className="border-l-[3px] border-[var(--violet-6)] bg-[var(--violet-2)] rounded-r-lg px-4 py-2 my-3 [&>p]:my-1">
            {children}
          </blockquote>
        );
      },

      // Styled table
      table({ children }: { children?: React.ReactNode }) {
        return (
          <div className="overflow-x-auto my-4 rounded-lg border border-[var(--border)]">
            <table className="w-full text-sm">{children}</table>
          </div>
        );
      },
      thead({ children }: { children?: React.ReactNode }) {
        return (
          <thead className="bg-[var(--surface-elevated)]">
            {children}
          </thead>
        );
      },
      th({ children }: { children?: React.ReactNode }) {
        return (
          <th className="px-3 py-2 text-left font-semibold text-[var(--foreground)] border-b border-[var(--border)]">
            {children}
          </th>
        );
      },
      td({ children }: { children?: React.ReactNode }) {
        return (
          <td className="px-3 py-2 border-b border-[var(--border-subtle)]">
            {children}
          </td>
        );
      },

      // Links
      a({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { node?: unknown }) {
        return (
          <a
            href={href}
            className="text-[var(--violet-9)] hover:text-[var(--violet-10)] underline decoration-[var(--violet-5)] underline-offset-2 transition-colors"
            target="_blank"
            rel="noopener noreferrer"
            {...props}
          >
            {children}
          </a>
        );
      },
    }),
    [onTimestampClick],
  );

  // ── User message ─────────────────────────────────────────────────────────
  if (isUser) {
    return (
      <motion.div
        variants={messageBubble}
        initial="initial"
        animate="animate"
        className="flex justify-end"
      >
        <div className="max-w-[75%]">
          {message.videoName && (
            <div className="flex items-center justify-end gap-1.5 text-[var(--text-tertiary)] text-xs mb-1.5 mr-1">
              <Film className="w-3 h-3" />
              {message.videoName}
            </div>
          )}
          <div className="px-4 py-3 rounded-2xl rounded-tr-sm bg-[var(--violet-9)] text-white shadow-md shadow-violet-500/10">
            <p className="text-[15px] leading-relaxed whitespace-pre-wrap">
              {message.content}
            </p>
          </div>
        </div>
      </motion.div>
    );
  }

  // ── Assistant message — clean prose, no bubble ───────────────────────────
  return (
    <motion.div
      variants={messageBubble}
      initial="initial"
      animate="animate"
      className="group/message"
    >
      <div className="flex items-start gap-3">
        {/* Avatar */}
        <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-gradient-to-br from-violet-500 to-violet-600 flex items-center justify-center shadow-lg shadow-violet-500/20 mt-0.5">
          <Sparkles className="w-4 h-4 text-white" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 pt-0.5">
          {message.isLoading ? (
            <div className="flex items-center gap-2 py-2">
              <div className="flex gap-1">
                <span
                  className="w-2 h-2 rounded-full bg-[var(--violet-7)] animate-bounce"
                  style={{ animationDelay: '0ms' }}
                />
                <span
                  className="w-2 h-2 rounded-full bg-[var(--violet-7)] animate-bounce"
                  style={{ animationDelay: '150ms' }}
                />
                <span
                  className="w-2 h-2 rounded-full bg-[var(--violet-7)] animate-bounce"
                  style={{ animationDelay: '300ms' }}
                />
              </div>
            </div>
          ) : (
            <>
              {/* Markdown content */}
              <div className="chat-prose text-[15px] leading-7 text-[var(--foreground)]">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeHighlight]}
                  components={markdownComponents}
                >
                  {displayContent}
                </ReactMarkdown>
                {isStreaming && <span className="streaming-cursor" />}
              </div>

              {/* Tool details */}
              {message.toolDetails && message.toolDetails.length > 0 && (
                <ReasoningPanel toolDetails={message.toolDetails} />
              )}

              {/* Suggestion chips */}
              {suggestions.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {suggestions.map((suggestion, idx) => (
                    <button
                      key={idx}
                      onClick={() => onSuggestionClick?.(suggestion)}
                      className="group/chip flex items-center gap-2 px-3.5 py-2 bg-[var(--surface)] text-[var(--foreground)] hover:bg-[var(--violet-2)] rounded-xl text-sm transition-all border border-[var(--border)] hover:border-[var(--violet-6)] hover:shadow-sm"
                    >
                      <span>{suggestion}</span>
                      <ArrowRight className="w-3.5 h-3.5 text-[var(--text-tertiary)] group-hover/chip:text-[var(--violet-8)] transition-colors" />
                    </button>
                  ))}
                </div>
              )}

              {/* Citation cards */}
              {message.sources && message.sources.length > 0 && (
                <CitationSection
                  sources={message.sources}
                  onTimestampClick={onTimestampClick}
                />
              )}

              {/* Hover actions (copy, retry) */}
              {!isStreaming && (
                <MessageActions
                  content={message.content}
                  onRetry={message.isError ? onRetryLast : undefined}
                  isError={message.isError}
                />
              )}
            </>
          )}
        </div>
      </div>
    </motion.div>
  );
});
