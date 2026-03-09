'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Send } from 'lucide-react';
import { apiClient, Clip } from '@/lib/api';
import { EditorChatMessages } from './EditorChatMessages';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolCalls?: number;
}

interface ToolStatus {
  name: string;
  status: 'running' | 'success' | 'error';
}

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
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [activeTools, setActiveTools] = useState<ToolStatus[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const generateId = () => Math.random().toString(36).substring(2, 9);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  };

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);
    setStreamingContent('');
    setActiveTools([]);

    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }

    try {
      const chatHistory = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      let finalResponse = '';
      let toolCallsMade = 0;

      for await (const event of apiClient.chatWithEditorAgentStream(
        userMessage.content,
        projectId,
        chatHistory,
        sessionId
      )) {
        switch (event.event) {
          case 'session':
            setSessionId(event.data.session_id);
            break;
          case 'thinking':
            break;
          case 'tool_start':
            setActiveTools((prev) => [
              ...prev,
              { name: event.data.tool || 'unknown', status: 'running' },
            ]);
            break;
          case 'tool_end':
            setActiveTools((prev) =>
              prev.map((t) =>
                t.name === event.data.tool
                  ? { ...t, status: event.data.success ? 'success' : 'error' }
                  : t
              )
            );
            break;
          case 'token':
            if (event.data.token) {
              setStreamingContent((prev) => prev + event.data.token);
            }
            break;
          case 'clips_updated':
            if (event.data.clips) {
              onClipsUpdated?.(event.data.clips);
            }
            break;
          case 'done':
            finalResponse = event.data.response || '';
            toolCallsMade = event.data.tool_calls_made || 0;
            break;
          case 'error':
            throw new Error(event.data.error || 'Unknown error');
        }
      }

      const assistantMessage: ChatMessage = {
        id: generateId(),
        role: 'assistant',
        content: finalResponse,
        timestamp: new Date(),
        toolCalls: toolCallsMade > 0 ? toolCallsMade : undefined,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setStreamingContent('');
      setActiveTools([]);
    } catch (error) {
      console.error('Chat error:', error);
      const errorMessage: ChatMessage = {
        id: generateId(),
        role: 'assistant',
        content:
          error instanceof Error
            ? `Sorry, I encountered an error: ${error.message}`
            : 'Sorry, I encountered an error processing your request. Please try again.',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      setStreamingContent('');
      setActiveTools([]);
    } finally {
      setIsLoading(false);
    }
  }, [inputValue, isLoading, messages, projectId, sessionId, onClipsUpdated]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
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
            onClick={handleSend}
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
