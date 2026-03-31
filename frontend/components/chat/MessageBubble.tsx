'use client';

import React, { memo } from 'react';
import { Sparkles, Film, Loader2, CheckCircle2, XCircle, Wrench, Terminal, ArrowRightCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import TimestampBadge from './TimestampBadge';
import { ReasoningPanel } from './ReasoningPanel';
import type { ToolDetail } from '@/hooks/useChatState';

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

function confidenceLabel(sources: ChatMessageSource[]): string {
  const scored = sources.filter((source) => typeof source.score === 'number');
  if (scored.length === 0) return 'Evidence available';

  const average = scored.reduce((sum, source) => sum + (source.score || 0), 0) / scored.length;
  if (average >= 0.8) return 'High confidence';
  if (average >= 0.5) return 'Medium confidence';
  return 'Low confidence';
}

export function ToolProgress({ tools }: { tools: ToolStatus[] }) {
  if (!tools || tools.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 mb-4 w-full">
      <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase tracking-wider mb-1 px-1">
        <Terminal className="w-3 h-3" />
        Process Log
      </div>
      <div className="space-y-2">
        {tools.map((tool, idx) => (
          <div 
            key={idx} 
            className={`flex items-center gap-2.5 p-3 rounded-lg border text-sm transition-all duration-300 animate-in slide-in-from-left-2 ${
              tool.status === 'running' 
                ? 'bg-blue-50/50 border-blue-100 text-blue-700' 
                : tool.status === 'success'
                ? 'bg-green-50/50 border-green-100 text-green-700'
                : 'bg-red-50/50 border-red-100 text-red-700'
            }`}
          >
            <div className={`flex-shrink-0 ${tool.status === 'running' ? 'animate-spin' : ''}`}>
              {tool.status === 'running' && <Loader2 className="w-4 h-4" />}
              {tool.status === 'success' && <CheckCircle2 className="w-4 h-4" />}
              {tool.status === 'error' && <XCircle className="w-4 h-4" />}
            </div>
            
            <div className="flex flex-col">
              <span className="font-medium">
                {tool.name.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')}
              </span>
              <span className="text-xs opacity-80">
                {tool.status === 'running' ? 'Executing...' : tool.status === 'success' ? 'Completed' : 'Failed'}
              </span>
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
      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
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
  const groupedSources = (message.sources || [])
    .slice()
    .sort((a, b) => (b.score || 0) - (a.score || 0))
    .reduce<Record<string, ChatMessageSource[]>>((acc, source) => {
      const key = source.videoTitle || source.videoId || 'Current video';
      if (!acc[key]) {
        acc[key] = [];
      }
      acc[key].push(source);
      return acc;
    }, {});
  
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

  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-in slide-in-from-bottom-2 duration-300`}
    >
      <div className={`max-w-[85%] ${isUser ? '' : ''}`}>
        {/* Assistant avatar and label */}
        {!isUser && (
          <div className="flex items-center gap-2 mb-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/30">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <span className="text-sm font-medium text-gray-600">QPrisma</span>
          </div>
        )}

        {/* Message bubble */}
        <div
          className={`p-4 rounded-2xl ${
            isUser
              ? 'bg-gradient-to-r from-indigo-500 to-purple-600 text-white rounded-tr-md shadow-lg shadow-indigo-500/20'
              : 'bg-white text-gray-800 rounded-tl-md shadow-md border border-gray-100'
          }`}
        >
          {message.isLoading ? (
            <div className="flex items-center gap-3 py-1">
              <TypingIndicator />
              <span className="text-sm text-gray-500">Analyzing...</span>
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
                <div className="text-sm leading-relaxed prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-strong:text-gray-900 prose-code:text-indigo-600 prose-code:bg-indigo-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none">
                  <ReactMarkdown>{displayContent}</ReactMarkdown>
                </div>
              )}

              {/* Agent Reasoning Panel — collapsible tool call details */}
              {!isUser && message.toolDetails && message.toolDetails.length > 0 && (
                <ReasoningPanel toolDetails={message.toolDetails} />
              )}

              {/* Suggestions Chips */}
              {!isUser && suggestions.length > 0 && (
                <div className="mt-4 pt-3 border-t border-gray-100 flex flex-col gap-2">
                  <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">Suggested Follow-ups</p>
                  <div className="flex flex-wrap gap-2">
                    {suggestions.map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => onSuggestionClick?.(suggestion)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-50 text-indigo-700 hover:bg-indigo-100 hover:text-indigo-800 rounded-full text-sm transition-colors border border-indigo-100 text-left"
                      >
                        <span className="flex-1">{suggestion}</span>
                        <ArrowRightCircle className="w-4 h-4 opacity-50" />
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Sources / Timestamps */}
              {!isUser && message.sources && message.sources.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-100">
                  <p className="text-xs text-gray-500 mb-2">
                    Referenced moments • {confidenceLabel(message.sources)}
                  </p>
                  <div className="space-y-2">
                    {Object.entries(groupedSources).slice(0, 3).map(([groupLabel, groupSources]) => (
                      <div key={groupLabel}>
                        <p className="text-[11px] text-gray-400 mb-1">{groupLabel}</p>
                        <div className="flex flex-wrap gap-2">
                          {groupSources.slice(0, 3).map((source, index) => (
                            <TimestampBadge
                              key={`${groupLabel}-${index}-${source.timestamp}`}
                              timestamp={source.timestamp}
                              type={source.type}
                              label={undefined}
                              onClick={() => onTimestampClick?.(source.timestamp)}
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                    {message.sources.length > 9 && (
                      <span className="text-xs text-gray-400 self-center block">
                        +{message.sources.length - 9} more references
                      </span>
                    )}
                  </div>
                </div>
              )}

              {!isUser && message.isError && onRetryLast && (
                <div className="mt-3 pt-3 border-t border-gray-100">
                  <button
                    onClick={onRetryLast}
                    className="text-sm px-3 py-1.5 rounded-lg bg-red-50 text-red-700 hover:bg-red-100 transition-colors"
                  >
                    Retry last prompt
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
});
