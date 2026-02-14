'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import WelcomeScreen from './WelcomeScreen';
import MessageList, { ChatMessageData, ToolStatus } from './MessageList';
import ChatInput from './ChatInput';
import { apiClient } from '@/lib/api';


interface ChatContainerProps {
  conversationId?: string;
  videoId?: string;
  videoName?: string;
  videoIds?: string[];
  videoNames?: string[];
  mode?: 'single' | 'library';
  onTimestampClick?: (timestamp: number) => void;
  onUploadVideo?: () => void;
  onBrowseLibrary?: () => void;
  userName?: string;
  initialMessages?: ChatMessageData[];
  initialSessionId?: string;
  onMessagesChange?: (messages: ChatMessageData[]) => void;
  onSessionIdChange?: (sessionId?: string) => void;
}

interface ChatSource {
  timestamp: number;
  type?: string;
  description?: string;
  score?: number;
  video_id?: string;
  video_title?: string;
}

export default function ChatContainer({
  conversationId,
  videoId,
  videoName,
  videoIds,
  videoNames,
  mode = 'single',
  onTimestampClick,
  onUploadVideo,
  onBrowseLibrary,
  userName,
  initialMessages = [],
  initialSessionId,
  onMessagesChange,
  onSessionIdChange,
}: ChatContainerProps) {
  const [messages, setMessages] = useState<ChatMessageData[]>(initialMessages);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [activeTools, setActiveTools] = useState<ToolStatus[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>(initialSessionId);
  const [lastSubmittedPrompt, setLastSubmittedPrompt] = useState<string>('');
  const abortControllerRef = useRef<AbortController | null>(null);

  const hasMessages = messages.length > 0;
  const isMultiVideo = videoIds && videoIds.length > 1;
  const hasVideo = isMultiVideo || !!videoId;

  const generateId = () => Math.random().toString(36).substring(2, 9);

  useEffect(() => {
    setMessages(initialMessages);
  }, [conversationId, initialMessages]);

  useEffect(() => {
    setSessionId(initialSessionId);
  }, [conversationId, initialSessionId]);

  useEffect(() => {
    onMessagesChange?.(messages);
  }, [messages, onMessagesChange]);

  useEffect(() => {
    onSessionIdChange?.(sessionId);
  }, [sessionId, onSessionIdChange]);

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || isLoading) return;

    const messageText = inputValue.trim();
    setLastSubmittedPrompt(messageText);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const userMessage: ChatMessageData = {
      id: generateId(),
      role: 'user',
      content: messageText,
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
      let streamedResponse = '';
      let sources: ChatSource[] = [];
      let toolCallsMade = 0;

      for await (const event of apiClient.chatWithAgentStream(
        userMessage.content,
        videoId || null,
        chatHistory,
        sessionId,
        videoIds,
        controller.signal
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
              streamedResponse += event.data.token;
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
      const resolvedResponse = finalResponse || streamedResponse;

      if (resolvedResponse) {
        const assistantMessage: ChatMessageData = {
          id: generateId(),
          role: 'assistant',
          content: resolvedResponse,
          timestamp: new Date(),
          sources: sources.map((s) => ({
            timestamp: s.timestamp,
            type: (s.type === 'visual' || s.type === 'audio' || s.type === 'entity') ? s.type : 'visual',
            description: s.description,
            score: s.score,
            videoId: s.video_id,
            videoTitle: s.video_title,
          })),
          toolCalls: toolCallsMade > 0 ? toolCallsMade : undefined,
        };

        setMessages((prev) => [...prev, assistantMessage]);
      }

      setStreamingContent('');
      setActiveTools([]);
    } catch (error) {
      const wasCancelled = error instanceof DOMException && error.name === 'AbortError';

      const errorMessage: ChatMessageData = {
        id: generateId(),
        role: 'assistant',
        content: wasCancelled
          ? 'Response stopped. You can retry your last message.'
          : error instanceof Error
            ? `Sorry, I encountered an error: ${error.message}`
            : 'Sorry, I encountered an error processing your request. Please try again.',
        timestamp: new Date(),
        isError: true,
      };

      setMessages((prev) => [...prev, errorMessage]);
      setStreamingContent('');
      setActiveTools([]);
    } finally {
      abortControllerRef.current = null;
      setIsLoading(false);
    }
  }, [inputValue, isLoading, messages, videoId, videoName, videoIds, mode, sessionId]);

  const handleQuickSuggestion = (suggestion: string) => {
    setInputValue(suggestion);
  };

  const handleRetryLast = useCallback(() => {
    if (!lastSubmittedPrompt || isLoading) {
      return;
    }
    setInputValue(lastSubmittedPrompt);
  }, [lastSubmittedPrompt, isLoading]);

  const handleCancel = useCallback(() => {
    if (!abortControllerRef.current) {
      return;
    }
    abortControllerRef.current.abort();
  }, []);

  // Show welcome screen if no messages and appropriate context
  const showWelcome = !hasMessages && !hasVideo;

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
            onRetryLast={lastSubmittedPrompt ? handleRetryLast : undefined}
          />

          {!hasVideo && (
            <div className="px-6 pb-2">
              <div className="max-w-3xl mx-auto rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
                Select or upload at least one video to start chatting.
              </div>
            </div>
          )}

          {/* Input */}
          <ChatInput
            value={inputValue}
            onChange={setInputValue}
            onSend={handleSend}
            onCancel={handleCancel}
            isLoading={isLoading}
            isDisabled={!hasVideo}
            mode={mode}
            onAttachVideo={mode === 'single' ? onUploadVideo : onBrowseLibrary}
            attachedVideos={
              isMultiVideo && videoIds && videoNames
                ? videoIds.map((id, i) => ({ id, name: videoNames?.[i] || 'Video' }))
                : mode === 'single' && videoId && videoName
                  ? [{ id: videoId, name: videoName }]
                  : []
            }
          />
        </>
      )}
    </div>
  );
}
