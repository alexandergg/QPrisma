'use client';

import React, { useCallback } from 'react';
import WelcomeScreen from './WelcomeScreen';
import MessageList, { ChatMessageData } from './MessageList';
import ChatInput from './ChatInput';
import { useChatState } from '@/hooks/useChatState';
import { useStreamingChat } from '@/hooks/useStreamingChat';


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
  const chatState = useChatState({
    initialMessages,
    initialSessionId,
    conversationId,
    onMessagesChange,
    onSessionIdChange,
  });

  const { messages, inputValue, setInputValue, isLoading, streamingContent, activeTools } = chatState;

  const { handleSend, handleCancel, lastSubmittedPrompt } = useStreamingChat({
    ...chatState,
    videoId,
    videoIds,
    videoName,
    mode,
  });

  const hasMessages = messages.length > 0;
  const isMultiVideo = videoIds && videoIds.length > 1;
  const hasVideo = isMultiVideo || !!videoId;

  const handleQuickSuggestion = (suggestion: string) => {
    setInputValue(suggestion);
  };

  const handleSendFromInput = useCallback(async () => {
    if (!inputValue.trim() || isLoading) return;
    const text = inputValue.trim();
    setInputValue('');
    await handleSend(text);
  }, [inputValue, isLoading, setInputValue, handleSend]);

  const handleRetryLast = useCallback(() => {
    if (!lastSubmittedPrompt || isLoading) return;
    setInputValue(lastSubmittedPrompt);
  }, [lastSubmittedPrompt, isLoading, setInputValue]);

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
            onSend={handleSendFromInput}
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
