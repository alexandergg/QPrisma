'use client';

import React, { useRef, useEffect } from 'react';
import { Wrench } from 'lucide-react';
import { MessageBubble, ToolProgress } from './MessageBubble';
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

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading, streamingContent, activeTools]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
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

        {/* Active Tools Display - Rendering as a distinct section in the chat stream */}
        {activeTools.length > 0 && (
           <div className="flex justify-start animate-in slide-in-from-bottom-2 duration-300">
             <div className="max-w-[85%] w-full">
               <div className="flex items-center gap-2 mb-2">
                 <div className="w-7 h-7 rounded-lg bg-gray-100 flex items-center justify-center border border-gray-200">
                   <Wrench className="w-3.5 h-3.5 text-gray-500" />
                 </div>
                 <span className="text-sm font-medium text-gray-500">Agent Tools</span>
               </div>
               
               <div className="ml-9">
                 <ToolProgress tools={activeTools} />
               </div>
             </div>
           </div>
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
