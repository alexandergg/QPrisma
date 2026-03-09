'use client';

import React, { useCallback, useRef, useEffect } from 'react';
import { Send } from 'lucide-react';
import type { Clip } from '@/lib/api';
import { EditorChatMessages } from './EditorChatMessages';
import { useChatState } from '@/hooks/useChatState';
import { useStreamingChat } from '@/hooks/useStreamingChat';

interface EditorChatProps {
  projectId: string;
  onClipsUpdated?: (clips: Clip[]) => void;
  onTimestampClick?: (timestamp: number) => void;
}

/**
 * Chat component specialized for the video editor
 */
export default function EditorChat({
  projectId,
  onClipsUpdated,
  onTimestampClick,
}: EditorChatProps) {
  const chatState = useChatState({});

  const {
    messages,
    inputValue,
    setInputValue,
    isLoading,
    streamingContent,
    activeTools,
  } = chatState;

  const { handleSend } = useStreamingChat({
    ...chatState,
    projectId,
    onClipsUpdated,
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  };

  const handleSendFromInput = useCallback(async () => {
    if (!inputValue.trim() || isLoading) return;
    const text = inputValue.trim();
    setInputValue('');
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }
    await handleSend(text);
  }, [inputValue, isLoading, setInputValue, handleSend]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendFromInput();
    }
  };

  const handleQuickAction = (message: string) => {
    setInputValue(message);
    inputRef.current?.focus();
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto">
        <EditorChatMessages
          messages={messages}
          streamingContent={streamingContent}
          activeTools={activeTools}
          isLoading={isLoading}
          onQuickAction={handleQuickAction}
          onTimestampClick={onTimestampClick}
          messagesEndRef={messagesEndRef}
        />
      </div>

      {/* Input Area */}
      <div className="border-t border-gray-200 p-4 bg-white">
        <div className="flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={inputValue}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask me to search, create clips, add subtitles..."
              disabled={isLoading}
              rows={1}
              className="w-full px-4 py-3 bg-gray-100 border border-transparent rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ maxHeight: '120px' }}
            />
          </div>
          <button
            onClick={handleSendFromInput}
            disabled={!inputValue.trim() || isLoading}
            className="p-3 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
        <p className="mt-2 text-xs text-gray-400 text-center">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
