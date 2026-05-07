'use client';

import React, { useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Film, Library, MessageSquare, ArrowRight } from 'lucide-react';
import WelcomeScreen from './WelcomeScreen';
import MessageList, { ChatMessageData } from './MessageList';
import ChatInput from './ChatInput';
import { useChatState } from '@/hooks/useChatState';
import { useStreamingChat } from '@/hooks/useStreamingChat';
import { staggerContainer, staggerItem } from '@/lib/animations';

const SINGLE_SUGGESTIONS = [
  'Summarize this video',
  'What are the key topics?',
  'Find important moments',
  'Generate a timeline',
];

const LIBRARY_SUGGESTIONS = [
  'Which videos discuss AI?',
  'Compare my videos',
  'Find tutorials',
  'Most discussed topics',
];

interface ChatContainerProps {
  videoId?: string;
  videoName?: string;
  videoIds?: string[];
  videoNames?: string[];
  mode?: 'single' | 'library';
  onTimestampClick?: (timestamp: number) => void;
  onUploadVideo?: () => void;
  onBrowseLibrary?: () => void;
  onSelectVideoById?: (videoId: string) => void;
  userName?: string;
  initialMessages?: ChatMessageData[];
  initialSessionId?: string;
  onMessagesChange?: (messages: ChatMessageData[]) => void;
  onSessionIdChange?: (sessionId?: string) => void;
}

export default function ChatContainer({
  videoId,
  videoName,
  videoIds,
  videoNames,
  mode = 'single',
  onTimestampClick,
  onUploadVideo,
  onBrowseLibrary,
  onSelectVideoById,
  userName,
  initialMessages = [],
  initialSessionId,
  onMessagesChange,
  onSessionIdChange,
}: ChatContainerProps) {
  const chatState = useChatState({
    initialMessages,
    initialSessionId,
    onMessagesChange,
    onSessionIdChange,
  });

  const { messages, inputValue, setInputValue, isLoading, streamingContent, activeTools, isThinking, thinkingStartTime } = chatState;

  const { handleSend, handleCancel, lastSubmittedPrompt } = useStreamingChat({
    ...chatState,
    videoId,
    videoIds,
    videoName,
    mode,
  });

  const hasMessages = messages.length > 0 || !!streamingContent;
  const isMultiVideo = videoIds && videoIds.length > 1;
  const hasVideo = isMultiVideo || !!videoId;
  const showCenteredInput = hasVideo && !hasMessages;
  const suggestions = mode === 'single' ? SINGLE_SUGGESTIONS : LIBRARY_SUGGESTIONS;
  const attachedVideos =
    isMultiVideo && videoIds && videoNames
      ? videoIds.map((id, i) => ({ id, name: videoNames?.[i] || 'Video' }))
      : mode === 'single' && videoId && videoName
        ? [{ id: videoId, name: videoName }]
        : [];

  const handleQuickSuggestion = useCallback((suggestion: string) => {
    if (isLoading) return;
    setInputValue('');
    handleSend(suggestion);
  }, [isLoading, setInputValue, handleSend]);

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

  const showWelcome = !hasMessages && !hasVideo;

  const subtitleText = useMemo(() => {
    if (!hasVideo) return 'Select a video to start chatting';
    if (isMultiVideo) return `Ask anything about your ${videoIds?.length} videos`;
    if (videoName) return `Ask anything about "${videoName}"`;
    return 'Ask anything about your video';
  }, [hasVideo, isMultiVideo, videoIds?.length, videoName]);

  return (
    <div className="flex flex-col h-full">
      <AnimatePresence mode="wait">
        {showWelcome ? (
          <motion.div
            key="welcome"
            className="flex-1 flex flex-col"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.15 } }}
          >
            <WelcomeScreen
              onUploadVideo={onUploadVideo}
              onBrowseLibrary={onBrowseLibrary}
              onQuickSuggestion={handleQuickSuggestion}
              onSelectVideo={onSelectVideoById}
              mode={mode}
              userName={userName}
            />
          </motion.div>
        ) : showCenteredInput ? (
          <motion.div
            key="centered"
            className="flex-1 flex flex-col items-center justify-center px-4"
            initial={{ opacity: 0, y: 20 }}
            animate={{
              opacity: 1,
              y: 0,
              transition: { duration: 0.4, ease: [0.4, 0, 0.2, 1] },
            }}
            exit={{ opacity: 0, y: -20, transition: { duration: 0.2 } }}
          >
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-[var(--violet-3)] bg-[var(--violet-1)] px-4 py-2 text-sm font-medium text-[var(--violet-11)] shadow-sm">
              {isMultiVideo ? <Library className="w-4 h-4" /> : <Film className="w-4 h-4" />}
              <span>{subtitleText}</span>
            </div>

            <div className="w-full max-w-2xl">
              <ChatInput
                variant="centered"
                value={inputValue}
                onChange={setInputValue}
                onSend={handleSendFromInput}
                onCancel={handleCancel}
                isLoading={isLoading}
                isDisabled={!hasVideo}
                mode={mode}
                autoFocus
                attachedVideos={attachedVideos}
              />
            </div>

            <motion.div
              variants={staggerContainer}
              initial="initial"
              animate="animate"
              className="grid grid-cols-2 gap-2 mt-4 max-w-2xl w-full"
            >
              {suggestions.map((suggestion) => (
                <motion.button
                  key={suggestion}
                  variants={staggerItem}
                  onClick={() => handleQuickSuggestion(suggestion)}
                  whileHover={{ y: -1, transition: { duration: 0.15 } }}
                  className="group flex items-center gap-3 text-left text-sm p-3 rounded-xl border border-gray-200 hover:border-violet-200 hover:bg-violet-50/50 transition-colors"
                >
                  <MessageSquare className="w-4 h-4 text-gray-400 group-hover:text-violet-600 flex-shrink-0" />
                  <span className="text-gray-600 group-hover:text-gray-900 flex-1">
                    {suggestion}
                  </span>
                  <ArrowRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-violet-500 opacity-0 group-hover:opacity-100 transition-all" />
                </motion.button>
              ))}
            </motion.div>
          </motion.div>
        ) : (
          <motion.div
            key="conversation"
            className="flex flex-col flex-1 min-h-0"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: { duration: 0.2 } }}
          >
            <MessageList
              messages={messages}
              isLoading={isLoading}
              onTimestampClick={onTimestampClick}
              streamingContent={streamingContent}
              activeTools={activeTools}
              onSuggestionClick={handleQuickSuggestion}
              onRetryLast={lastSubmittedPrompt ? handleRetryLast : undefined}
              isThinking={isThinking}
              thinkingStartTime={thinkingStartTime}
            />

            {!hasVideo && (
              <div className="px-6 pb-2">
                <div className="max-w-3xl mx-auto rounded-xl border border-[var(--violet-3)] bg-[var(--violet-1)] px-4 py-2 text-sm text-[var(--violet-11)]">
                  Select or upload at least one video to start chatting.
                </div>
              </div>
            )}

            <ChatInput
              variant="bottom"
              value={inputValue}
              onChange={setInputValue}
              onSend={handleSendFromInput}
              onCancel={handleCancel}
              isLoading={isLoading}
              isDisabled={!hasVideo}
              mode={mode}
              onAttachVideo={mode === 'single' ? onUploadVideo : onBrowseLibrary}
              attachedVideos={attachedVideos}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
