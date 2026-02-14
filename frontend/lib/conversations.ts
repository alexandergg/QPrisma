import type { ChatMessageData, ChatMessageSource } from '@/components/chat';

export type ConversationMode = 'single' | 'library';

export interface ConversationSummary {
  id: string;
  title: string;
  videoId?: string;
  videoIds?: string[];
  videoName?: string;
  videoNames?: string[];
  lastMessage?: string;
  updatedAt: Date;
  mode: ConversationMode;
  sessionId?: string;
  messageCount?: number;
}

interface StoredConversationSummary {
  id: string;
  title: string;
  videoId?: string;
  videoIds?: string[];
  videoName?: string;
  videoNames?: string[];
  lastMessage?: string;
  updatedAt: string;
  mode: ConversationMode;
  sessionId?: string;
  messageCount?: number;
}

interface StoredMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  sources?: ChatMessageSource[];
  isLoading?: boolean;
  videoName?: string;
  toolCalls?: number;
  isError?: boolean;
}

const CONVERSATIONS_KEY = 'qprisma_conversations';
const MESSAGES_KEY = 'qprisma_conversation_messages';

function isBrowser(): boolean {
  return typeof window !== 'undefined';
}

export function loadConversations(): ConversationSummary[] {
  if (!isBrowser()) {
    return [];
  }

  const raw = localStorage.getItem(CONVERSATIONS_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw) as StoredConversationSummary[];
    return parsed
      .map((item) => ({
        ...item,
        updatedAt: new Date(item.updatedAt),
      }))
      .sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime());
  } catch {
    return [];
  }
}

export function saveConversations(conversations: ConversationSummary[]): void {
  if (!isBrowser()) {
    return;
  }

  const toStore: StoredConversationSummary[] = conversations.map((item) => ({
    ...item,
    updatedAt: item.updatedAt.toISOString(),
  }));
  localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(toStore));
}

export function getConversationById(conversationId: string): ConversationSummary | undefined {
  return loadConversations().find((conversation) => conversation.id === conversationId);
}

export function upsertConversation(conversation: ConversationSummary): ConversationSummary[] {
  const existing = loadConversations();
  const filtered = existing.filter((item) => item.id !== conversation.id);
  const updated = [conversation, ...filtered].sort(
    (a, b) => b.updatedAt.getTime() - a.updatedAt.getTime()
  );
  saveConversations(updated);
  return updated;
}

export function removeConversation(conversationId: string): ConversationSummary[] {
  const updated = loadConversations().filter((conversation) => conversation.id !== conversationId);
  saveConversations(updated);

  if (isBrowser()) {
    const messages = loadAllStoredMessages();
    if (conversationId in messages) {
      delete messages[conversationId];
      localStorage.setItem(MESSAGES_KEY, JSON.stringify(messages));
    }
  }

  return updated;
}

function loadAllStoredMessages(): Record<string, StoredMessage[]> {
  if (!isBrowser()) {
    return {};
  }

  const raw = localStorage.getItem(MESSAGES_KEY);
  if (!raw) {
    return {};
  }

  try {
    return JSON.parse(raw) as Record<string, StoredMessage[]>;
  } catch {
    return {};
  }
}

export function loadConversationMessages(conversationId: string): ChatMessageData[] {
  const allMessages = loadAllStoredMessages();
  const messages = allMessages[conversationId] || [];

  return messages.map((message) => ({
    ...message,
    timestamp: new Date(message.timestamp),
  }));
}

export function saveConversationMessages(
  conversationId: string,
  messages: ChatMessageData[]
): void {
  if (!isBrowser()) {
    return;
  }

  const allMessages = loadAllStoredMessages();
  allMessages[conversationId] = messages.map((message) => ({
    ...message,
    timestamp: message.timestamp.toISOString(),
  }));

  localStorage.setItem(MESSAGES_KEY, JSON.stringify(allMessages));
}

export function getConversationTitle(messages: ChatMessageData[]): string {
  const firstUserMessage = messages.find((message) => message.role === 'user')?.content?.trim();
  if (!firstUserMessage) {
    return 'New Conversation';
  }

  return firstUserMessage.length > 60
    ? `${firstUserMessage.slice(0, 57).trim()}...`
    : firstUserMessage;
}

export function getConversationPreview(messages: ChatMessageData[]): string | undefined {
  const lastMessage = [...messages].reverse().find((message) => message.role === 'assistant')
    ?? [...messages].reverse().find((message) => message.role === 'user');

  const content = lastMessage?.content?.trim();
  if (!content) {
    return undefined;
  }

  return content.length > 80 ? `${content.slice(0, 77).trim()}...` : content;
}