'use client';

import React, { useState, useCallback } from 'react';
import WelcomeScreen from './WelcomeScreen';
import MessageList, { ChatMessageData, ToolStatus } from './MessageList';
import ChatInput from './ChatInput';
import { apiClient } from '@/lib/api';


interface ChatContainerProps {
  videoId?: string;
  videoName?: string;
  mode?: 'single' | 'library';
  onTimestampClick?: (timestamp: number) => void;
  onUploadVideo?: () => void;
  onBrowseLibrary?: () => void;
  userName?: string;
}

interface ChatSource {
  timestamp: number;
  type?: string;
  description?: string;
  score?: number;
}

export default function ChatContainer({
  videoId,
  videoName,
  mode = 'single',
  onTimestampClick,
  onUploadVideo,
  onBrowseLibrary,
  userName,
}: ChatContainerProps) {
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [activeTools, setActiveTools] = useState<ToolStatus[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>();

  const hasMessages = messages.length > 0;
  const hasVideo = mode === 'library' || (mode === 'single' && videoId);

  const generateId = () => Math.random().toString(36).substring(2, 9);

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage: ChatMessageData = {
      id: generateId(),
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date(),
      videoName: mode === 'single' ? videoName : undefined,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);
    setStreamingContent('');
    setActiveTools([]);

    try {
      // Build chat history for context
      const chatHistory = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      // Use streaming agent API
      let finalResponse = '';
      let sources: ChatSource[] = [];
      let toolCallsMade = 0;

      for await (const event of apiClient.chatWithAgentStream(
        userMessage.content,
        videoId || null,  // Always send videoId when available
        chatHistory,
        sessionId
      )) {
        switch (event.event) {
          case 'session':
            setSessionId(event.data.session_id);
            break;

          case 'thinking':
            // Could show a thinking indicator
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

          case 'sources':
            sources = event.data.sources || [];
            break;

          case 'done':
            finalResponse = event.data.response || '';
            toolCallsMade = event.data.tool_calls_made || 0;
            break;

          case 'error':
            throw new Error(event.data.error || 'Unknown error');
        }
      }

      // Create final assistant message
      const assistantMessage: ChatMessageData = {
        id: generateId(),
        role: 'assistant',
        content: finalResponse,
        timestamp: new Date(),
        sources: sources.map((s) => ({
          timestamp: s.timestamp,
          type: (s.type === 'visual' || s.type === 'audio' || s.type === 'entity') ? s.type : 'visual',
          description: s.description,
          score: s.score,
        })),
        toolCalls: toolCallsMade > 0 ? toolCallsMade : undefined,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setStreamingContent('');
      setActiveTools([]);
    } catch (error) {
      console.error('Chat error:', error);

      const errorMessage: ChatMessageData = {
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
  }, [inputValue, isLoading, messages, videoId, videoName, mode, sessionId]);

  const handleQuickSuggestion = (suggestion: string) => {
    setInputValue(suggestion);
  };

  // Show welcome screen if no messages and appropriate context
  const showWelcome = !hasMessages && (!hasVideo || mode === 'library');

  return (
    <div className="flex flex-col h-full">
      {showWelcome ? (
        <WelcomeScreen
          onUploadVideo={onUploadVideo}
          onBrowseLibrary={onBrowseLibrary}
          onQuickSuggestion={handleQuickSuggestion}
          mode={mode}
          userName={userName}
        />
      ) : (
        <>
          {/* Messages */}
          <MessageList
            messages={messages}
            isLoading={isLoading}
            onTimestampClick={onTimestampClick}
            streamingContent={streamingContent}
            activeTools={activeTools}
            onSuggestionClick={handleQuickSuggestion}
          />

          {/* Input */}
          <ChatInput
            value={inputValue}
            onChange={setInputValue}
            onSend={handleSend}
            isLoading={isLoading}
            isDisabled={!hasVideo && mode === 'single'}
            mode={mode}
            attachedVideos={
              mode === 'single' && videoId && videoName
                ? [{ id: videoId, name: videoName }]
                : []
            }
          />
        </>
      )}
    </div>
  );
}
