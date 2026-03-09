/**
 * useChatState Hook
 *
 * Manages shared chat state used by ChatContainer.
 * Holds messages, input value, loading/streaming state, active tools,
 * and an optional session ID. Syncs with external callbacks when provided.
 */

import { useState, useEffect } from 'react';
import type { ToolStatus } from '@/components/chat/MessageBubble';

// =============================================================================
// Types
// =============================================================================

/** Generic chat message used by Chat. */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  sources?: ChatMessageSource[];
  isLoading?: boolean;
  videoName?: string;
  toolCalls?: number;
  isError?: boolean;
}

export interface ChatMessageSource {
  timestamp: number;
  type: 'visual' | 'audio' | 'entity';
  description?: string;
  score?: number;
  videoId?: string;
  videoTitle?: string;
}

export interface UseChatStateOptions {
  /** Seed the message list (e.g. when restoring a conversation). */
  initialMessages?: ChatMessage[];
  /** Seed the session id (e.g. when restoring a conversation). */
  initialSessionId?: string;
  /** External key used to detect conversation switches (resets state). */
  conversationId?: string;
  /** Called whenever the messages array changes. */
  onMessagesChange?: (messages: ChatMessage[]) => void;
  /** Called whenever the session id changes. */
  onSessionIdChange?: (sessionId?: string) => void;
}

export interface UseChatStateReturn {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  inputValue: string;
  setInputValue: React.Dispatch<React.SetStateAction<string>>;
  isLoading: boolean;
  setIsLoading: React.Dispatch<React.SetStateAction<boolean>>;
  streamingContent: string;
  setStreamingContent: React.Dispatch<React.SetStateAction<string>>;
  activeTools: ToolStatus[];
  setActiveTools: React.Dispatch<React.SetStateAction<ToolStatus[]>>;
  sessionId: string | undefined;
  setSessionId: React.Dispatch<React.SetStateAction<string | undefined>>;
}

// =============================================================================
// Hook
// =============================================================================

export function useChatState(options: UseChatStateOptions = {}): UseChatStateReturn {
  const {
    initialMessages = [],
    initialSessionId,
    conversationId,
    onMessagesChange,
    onSessionIdChange,
  } = options;

  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [activeTools, setActiveTools] = useState<ToolStatus[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>(initialSessionId);

  // Adjust state when the conversation switches (React-recommended pattern)
  const [prevConversationId, setPrevConversationId] = useState(conversationId);
  if (prevConversationId !== conversationId) {
    setPrevConversationId(conversationId);
    setMessages(initialMessages);
    setSessionId(initialSessionId);
  }

  // Notify parent about message changes
  useEffect(() => {
    onMessagesChange?.(messages);
  }, [messages, onMessagesChange]);

  // Notify parent about session id changes
  useEffect(() => {
    onSessionIdChange?.(sessionId);
  }, [sessionId, onSessionIdChange]);

  return {
    messages,
    setMessages,
    inputValue,
    setInputValue,
    isLoading,
    setIsLoading,
    streamingContent,
    setStreamingContent,
    activeTools,
    setActiveTools,
    sessionId,
    setSessionId,
  };
}
