'use client';

import React, { useState } from 'react';
import { Film, Library, MessageSquare, Trash2 } from 'lucide-react';
import type { ChatMode } from './Sidebar';

interface Conversation {
  id: string;
  title: string;
  videoId?: string;
  videoName?: string;
  lastMessage?: string;
  updatedAt: Date;
  mode: ChatMode;
}

interface ConversationsListProps {
  conversations: Conversation[];
  activeConversationId?: string;
  onSelectConversation: (id: string) => void;
  onDeleteConversation?: (id: string) => void;
}

/**
 * Scrollable list of recent conversations for the sidebar.
 */
export function ConversationsList({
  conversations,
  activeConversationId,
  onSelectConversation,
  onDeleteConversation,
}: ConversationsListProps) {
  const [hoveredConversation, setHoveredConversation] = useState<string | null>(null);

  if (conversations.length === 0) {
    return (
      <div className="text-center py-8">
        <MessageSquare className="w-8 h-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-400">No conversations yet</p>
        <p className="text-xs text-gray-400 mt-1">Start a new chat to begin</p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {conversations.map((conversation) => {
        const isActive = activeConversationId === conversation.id;
        const isHovered = hoveredConversation === conversation.id;

        return (
          <div
            key={conversation.id}
            onMouseEnter={() => setHoveredConversation(conversation.id)}
            onMouseLeave={() => setHoveredConversation(null)}
            onClick={() => onSelectConversation(conversation.id)}
            className={`group relative flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer transition-all ${
              isActive
                ? 'bg-indigo-50 border border-indigo-200'
                : 'hover:bg-gray-50'
            }`}
          >
            {/* Icon */}
            <div
              className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                isActive
                  ? 'bg-indigo-500 text-white'
                  : 'bg-gray-100 text-gray-500 group-hover:bg-gray-200'
              }`}
            >
              {conversation.mode === 'library' ? (
                <Library className="w-4 h-4" />
              ) : (
                <Film className="w-4 h-4" />
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <p
                className={`text-sm font-medium truncate ${
                  isActive ? 'text-indigo-700' : 'text-gray-700'
                }`}
              >
                {conversation.title}
              </p>
              {conversation.videoName && (
                <p className="text-xs text-gray-400 truncate">
                  {conversation.videoName}
                </p>
              )}
            </div>

            {/* Actions */}
            {isHovered && onDeleteConversation && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteConversation(conversation.id);
                }}
                className="p-1.5 hover:bg-red-100 rounded-lg text-gray-400 hover:text-red-500 transition-colors"
                aria-label={`Delete conversation: ${conversation.title}`}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

export type { Conversation };
