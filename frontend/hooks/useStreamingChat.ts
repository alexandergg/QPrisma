/**
 * useStreamingChat Hook
 *
 * Encapsulates the streaming send / cancel / retry logic used by
 * ChatContainer. Processes SSE events from `chatWithAgentStream`
 * through a single event loop.
 */

import { useCallback, useRef, useState } from 'react';
import type { ToolStatus } from '@/components/chat/MessageBubble';
import { apiClient } from '@/lib/api';
import type { ChatMessage, ChatMessageSource } from './useChatState';

// =============================================================================
// Types
// =============================================================================

interface ChatSource {
  timestamp: number;
  type?: string;
  description?: string;
  score?: number;
  video_id?: string;
  video_title?: string;
}

export interface UseStreamingChatOptions {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setStreamingContent: React.Dispatch<React.SetStateAction<string>>;
  setActiveTools: React.Dispatch<React.SetStateAction<ToolStatus[]>>;
  setIsLoading: React.Dispatch<React.SetStateAction<boolean>>;
  sessionId: string | undefined;
  setSessionId: React.Dispatch<React.SetStateAction<string | undefined>>;

  /** Single video id (single mode). */
  videoId?: string;
  /** Multiple video ids (library mode). */
  videoIds?: string[];
  /** Video name attached to user messages (single mode). */
  videoName?: string;
  /** Chat mode – only used to decide whether to attach videoName. */
  mode?: 'single' | 'library';
}

export interface UseStreamingChatReturn {
  /** Send the current input as a user message and stream the response. */
  handleSend: (content: string) => Promise<void>;
  /** Abort the in-flight streaming request. */
  handleCancel: () => void;
  /** Re-populate input with the last submitted prompt (caller triggers send). */
  handleRetryLast: () => void;
  /** The last prompt that was submitted (used to show retry affordance). */
  lastSubmittedPrompt: string;
}

// =============================================================================
// Helpers
// =============================================================================

const generateId = () => Math.random().toString(36).substring(2, 9);

// =============================================================================
// Hook
// =============================================================================

export function useStreamingChat(options: UseStreamingChatOptions): UseStreamingChatReturn {
  const {
    messages,
    setMessages,
    setStreamingContent,
    setActiveTools,
    setIsLoading,
    sessionId,
    setSessionId,
    videoId,
    videoIds,
    videoName,
    mode,
  } = options;

  const [lastSubmittedPrompt, setLastSubmittedPrompt] = useState('');
  const abortControllerRef = useRef<AbortController | null>(null);

  const commitAssistantMessage = useCallback(
    (
      response: string,
      sources: ChatSource[],
      toolCallsMade: number,
    ) => {
      if (!response) {
        return;
      }

      const mappedSources: ChatMessageSource[] | undefined =
        sources.length > 0
          ? sources.map((s) => ({
              timestamp: s.timestamp,
              type:
                s.type === 'visual' || s.type === 'audio' || s.type === 'entity'
                  ? s.type
                  : ('visual' as const),
              description: s.description,
              score: s.score,
              videoId: s.video_id,
              videoTitle: s.video_title,
            }))
          : undefined;

      const assistantMessage: ChatMessage = {
        id: generateId(),
        role: 'assistant',
        content: response,
        timestamp: new Date(),
        sources: mappedSources,
        toolCalls: toolCallsMade > 0 ? toolCallsMade : undefined,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setStreamingContent('');
      setActiveTools([]);
    },
    [setActiveTools, setMessages, setStreamingContent],
  );

  const handleSend = useCallback(
    async (content: string) => {
      const messageText = content.trim();
      if (!messageText) return;

      // Diagnostic: log videoId to help debug "no video loaded" issues
      if (typeof window !== 'undefined') {
        console.log('[useStreamingChat] handleSend called', {
          videoId,
          videoName,
          mode,
          sessionId,
          hasVideoIds: !!videoIds?.length,
        });
      }

      setLastSubmittedPrompt(messageText);

      const controller = new AbortController();
      abortControllerRef.current = controller;

      const userMessage: ChatMessage = {
        id: generateId(),
        role: 'user',
        content: messageText,
        timestamp: new Date(),
        videoName: mode === 'single' ? videoName : undefined,
      };

      setMessages((prev) => [...prev, userMessage]);
      setIsLoading(true);
      setStreamingContent('');
      setActiveTools([]);

      try {
        // Build chat history from existing messages
        const chatHistory = messages.map((m) => ({
          role: m.role,
          content: m.content,
        }));

        let finalResponse = '';
        let streamedResponse = '';
        let sources: ChatSource[] = [];
        let toolCallsMade = 0;
        let responseCommitted = false;

        const stream = apiClient.chatWithAgentStream(
          messageText,
          videoId || null,
          chatHistory,
          sessionId,
          videoIds,
          controller.signal,
        );
        for await (const event of stream) {
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
                    : t,
                ),
              );
              break;

            case 'token':
              if (event.data.token) {
                streamedResponse += event.data.token;
                setStreamingContent((prev) => prev + event.data.token);
              }
              break;

            case 'sources':
              sources = (event.data.sources as ChatSource[] | undefined) || [];
              break;

            case 'done':
              finalResponse = event.data.response || '';
              toolCallsMade = event.data.tool_calls_made || 0;
              commitAssistantMessage(
                finalResponse || streamedResponse,
                sources,
                toolCallsMade,
              );
              responseCommitted = true;
              break;

            case 'error':
              throw new Error(event.data.error || 'Unknown error');
          }

          if (responseCommitted) {
            break;
          }
        }

        if (!responseCommitted) {
          commitAssistantMessage(finalResponse || streamedResponse, sources, toolCallsMade);
          setStreamingContent('');
          setActiveTools([]);
        }
      } catch (error) {
        const wasCancelled =
          error instanceof DOMException && error.name === 'AbortError';

        const errorMessage: ChatMessage = {
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
    },
    [
      messages,
      setMessages,
      setStreamingContent,
      setActiveTools,
      setIsLoading,
      sessionId,
      setSessionId,
      videoId,
      videoIds,
      videoName,
      mode,
      commitAssistantMessage,
    ],
  );

  const handleCancel = useCallback(() => {
    if (!abortControllerRef.current) return;
    abortControllerRef.current.abort();
  }, []);

  const handleRetryLast = useCallback(() => {
    if (!lastSubmittedPrompt) return;
    // The caller is expected to trigger handleSend with the returned prompt
    // (e.g. by setting inputValue, which is outside this hook's scope).
  }, [lastSubmittedPrompt]);

  return {
    handleSend,
    handleCancel,
    handleRetryLast,
    lastSubmittedPrompt,
  };
}
