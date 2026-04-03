'use client';

import React, { useRef, useEffect } from 'react';
import { MessageBubble } from './MessageBubble';
import { LiveReasoningPanel } from './ReasoningPanel';
import type { ChatMessageData, ChatMessageSource, ToolStatus } from './MessageBubble';

// Re-export types for backward compatibility
export type { ChatMessageData, ChatMessageSource, ToolStatus };

interface MessageListProps {
  messages: ChatMessageData[];
  isLoading?: boolean;
  onTimestampClick?: (timestamp: number) => void;
  onSuggestionClick?: (suggestion: string) => void;
  streamingContent?: string;
  activeTools?: ToolStatus[];
  onRetryLast?: () => void;
}

export default function MessageList({ messages, isLoading, onTimestampClick, onSuggestionClick, streamingContent, activeTools = [], onRetryLast }: MessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const isStreamingRef = useRef(false);

  useEffect(() => {
    isStreamingRef.current = !!streamingContent;
  }, [streamingContent]);

  // Scroll to bottom — throttled during streaming to prevent jitter
  useEffect(() => {
    if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);

    const delay = isStreamingRef.current ? 150 : 0;
    const behavior: ScrollBehavior = isStreamingRef.current ? 'auto' : 'smooth';

    scrollTimeoutRef.current = setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior });
    }, delay);

    return () => {
      if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
    };
  }, [messages, isLoading, streamingContent, activeTools]);

  return (
    <div className="flex-1 overflow-y-auto min-h-0 px-4 py-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            onTimestampClick={onTimestampClick}
            onSuggestionClick={onSuggestionClick}
            onRetryLast={onRetryLast}
          />
        ))}

        {/* Live Reasoning Panel — shows tool progress during streaming */}
        {activeTools.length > 0 && (
          <LiveReasoningPanel tools={activeTools} />
        )}

        {/* Streaming response */}
        {streamingContent && (
          <MessageBubble
            message={{
              id: 'streaming',
              role: 'assistant',
              content: streamingContent,
              timestamp: new Date(),
            }}
          />
        )}

        {/* Loading indicator for pending response (only if not streaming and not showing tools) */}
        {isLoading && !streamingContent && activeTools.length === 0 && (
          <MessageBubble
            message={{
              id: 'loading',
              role: 'assistant',
              content: '',
              timestamp: new Date(),
              isLoading: true,
            }}
          />
        )}

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
