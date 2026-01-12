'use client';

import React, { useRef, useEffect } from 'react';
import { Sparkles, User, Play, Film } from 'lucide-react';
import TimestampBadge from './TimestampBadge';

export interface ChatMessageSource {
  timestamp: number;
  type: 'visual' | 'audio' | 'entity';
  description?: string;
  score?: number;
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
}

interface MessageListProps {
  messages: ChatMessageData[];
  isLoading?: boolean;
  onTimestampClick?: (timestamp: number) => void;
  streamingContent?: string;
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

function MessageBubble({
  message,
  onTimestampClick,
}: {
  message: ChatMessageData;
  onTimestampClick?: (timestamp: number) => void;
}) {
  const isUser = message.role === 'user';

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

              {/* Message content */}
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>

              {/* Sources / Timestamps */}
              {!isUser && message.sources && message.sources.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-100">
                  <p className="text-xs text-gray-400 mb-2">Referenced moments:</p>
                  <div className="flex flex-wrap gap-2">
                    {message.sources.slice(0, 5).map((source, index) => (
                      <TimestampBadge
                        key={index}
                        timestamp={source.timestamp}
                        type={source.type}
                        onClick={() => onTimestampClick?.(source.timestamp)}
                      />
                    ))}
                    {message.sources.length > 5 && (
                      <span className="text-xs text-gray-400 self-center">
                        +{message.sources.length - 5} more
                      </span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MessageList({ messages, isLoading, onTimestampClick, streamingContent }: MessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading, streamingContent]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            onTimestampClick={onTimestampClick}
          />
        ))}

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

        {/* Loading indicator for pending response (only if not streaming) */}
        {isLoading && !streamingContent && (
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
