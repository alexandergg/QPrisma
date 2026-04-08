/**
 * useStreamingChat Hook
 *
 * Encapsulates the streaming send / cancel / retry logic used by
 * ChatContainer. Processes SSE events from `chatWithAgentStream`
 * through a single event loop.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ToolStatus } from '@/components/chat/MessageBubble';
import { apiClient } from '@/lib/api';
import type { ChatMessage, ChatMessageSource, ToolDetail } from './useChatState';

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
  const tokenBufferRef = useRef('');
  const rafIdRef = useRef<number | undefined>(undefined);

  // Clean up rAF on unmount
  useEffect(() => {
    return () => {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
      }
    };
  }, []);

  const commitAssistantMessage = useCallback(
    (
      response: string,
      sources: ChatSource[],
      toolCallsMade: number,
      toolDetails?: ToolDetail[],
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
        toolDetails: toolDetails && toolDetails.length > 0 ? toolDetails : undefined,
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
        // Local mirror of active tools — React state is async so we need
        // a synchronous copy to read from at commit time.
        const localTools: Array<{ name: string; status: string; description?: string }> = [];
        const toolDescriptions: Record<string, string> = {};

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

            case 'tool_start': {
              const toolName = event.data.tool || 'unknown';
              localTools.push({ name: toolName, status: 'running' });
              setActiveTools((prev) => [
                ...prev,
                { name: toolName, status: 'running' },
              ]);
              break;
            }

            case 'tool_args':
              if (event.data.tool && event.data.description) {
                toolDescriptions[event.data.tool] = event.data.description;
                const lt = localTools.find((t) => t.name === event.data.tool && t.status === 'running');
                if (lt) lt.description = event.data.description;
                setActiveTools((prev) =>
                  prev.map((t) =>
                    t.name === event.data.tool
                      ? { ...t, description: event.data.description }
                      : t,
                  ),
                );
              }
              break;

            case 'tool_end': {
              const newStatus = event.data.success ? 'success' : 'error';
              const lt = localTools.find((t) => t.name === event.data.tool && t.status === 'running');
              if (lt) lt.status = newStatus;
              setActiveTools((prev) =>
                prev.map((t) =>
                  t.name === event.data.tool
                    ? { ...t, status: event.data.success ? 'success' : 'error' }
                    : t,
                ),
              );
              break;
            }

            case 'token':
              if (event.data.token) {
                streamedResponse += event.data.token;
                tokenBufferRef.current += event.data.token;
                if (!rafIdRef.current) {
                  rafIdRef.current = requestAnimationFrame(() => {
                    const buffered = tokenBufferRef.current;
                    tokenBufferRef.current = '';
                    rafIdRef.current = undefined;
                    setStreamingContent((prev) => prev + buffered);
                  });
                }
              }
              break;

            case 'sources':
              sources = (event.data.sources as ChatSource[] | undefined) || [];
              break;

            case 'done': {
              finalResponse = event.data.response || '';
              toolCallsMade = event.data.tool_calls_made || 0;
              // Build tool details from our synchronous local mirror
              const finalToolDetails: ToolDetail[] = localTools.map((t) => ({
                name: t.name,
                status: (t.status === 'error' ? 'error' : 'success') as 'success' | 'error',
                description: toolDescriptions[t.name] || t.description,
              }));
              commitAssistantMessage(
                finalResponse || streamedResponse,
                sources,
                toolCallsMade,
                finalToolDetails,
              );
              responseCommitted = true;
              break;
            }

            case 'error':
              throw new Error(event.data.error || 'Unknown error');
          }

          if (responseCommitted) {
            break;
          }
        }

        if (!responseCommitted) {
          // Build tool details from the synchronous local mirror
          const fallbackToolDetails: ToolDetail[] = localTools.map((t) => ({
            name: t.name,
            status: (t.status === 'error' ? 'error' : 'success') as 'success' | 'error',
            description: toolDescriptions[t.name] || t.description,
          }));
          commitAssistantMessage(
            finalResponse || streamedResponse,
            sources,
            toolCallsMade,
            fallbackToolDetails,
          );
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
    // Flush buffered tokens before aborting
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = undefined;
    }
    if (tokenBufferRef.current) {
      setStreamingContent((prev) => prev + tokenBufferRef.current);
      tokenBufferRef.current = '';
    }
    abortControllerRef.current.abort();
  }, [setStreamingContent]);

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
