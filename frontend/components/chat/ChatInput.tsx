'use client';

import React, { useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Plus, Film, X, Square } from 'lucide-react';

interface AttachedVideo {
  id: string;
  name: string;
}

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onCancel?: () => void;
  onAttachVideo?: () => void;
  attachedVideos?: AttachedVideo[];
  onRemoveVideo?: (id: string) => void;
  isLoading?: boolean;
  isDisabled?: boolean;
  placeholder?: string;
  mode?: 'single' | 'library';
  variant?: 'centered' | 'bottom';
}

export default function ChatInput({
  value,
  onChange,
  onSend,
  onCancel,
  onAttachVideo,
  attachedVideos = [],
  onRemoveVideo,
  isLoading = false,
  isDisabled = false,
  placeholder,
  mode = 'single',
  variant = 'bottom',
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const scrollHeight = textareaRef.current.scrollHeight;
      const lineHeight = 24;
      textareaRef.current.style.height = `${Math.min(scrollHeight, lineHeight * 5)}px`;
    }
  }, [value]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isDisabled && !isLoading && value.trim()) {
        onSend();
      }
    }
  };

  const defaultPlaceholder =
    mode === 'single'
      ? 'Ask anything about your video...'
      : 'Search across all your videos...';

  const hintText = isDisabled
    ? 'Select or upload a video to start chatting'
    : 'Press Enter to send · Shift+Enter for new line';

  const canSend = value.trim() && !isDisabled && !isLoading;

  return (
    <div className={variant === 'bottom' ? 'border-t border-[var(--border-subtle)] bg-[var(--surface)]/80 backdrop-blur-xl' : ''}>
      <div className={variant === 'bottom' ? 'max-w-3xl mx-auto p-4' : ''}>
        {/* Attached Videos Bar */}
        {attachedVideos.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {attachedVideos.map((video) => (
              <div
                key={video.id}
                className="inline-flex items-center gap-2 px-3 py-1.5 bg-[var(--violet-2)] text-[var(--violet-9)] rounded-full text-sm border border-[var(--violet-4)]"
              >
                <Film className="w-3 h-3" />
                <span className="max-w-[150px] truncate">{video.name}</span>
                {onRemoveVideo && (
                  <button
                    onClick={() => onRemoveVideo(video.id)}
                    className="p-0.5 hover:bg-[var(--violet-3)] rounded-full transition-colors"
                    aria-label={`Remove ${video.name}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Input Container */}
        <div className={`relative bg-[var(--surface)] rounded-2xl border border-[var(--border)] focus-within:border-[var(--violet-6)] focus-within:ring-4 focus-within:ring-[var(--violet-4)]/30 transition-all ${
          variant === 'centered' ? 'shadow-xl' : 'shadow-lg'
        }`}>
          <div className="flex items-end gap-2 p-3">
            {/* Attach Video Button */}
            {variant === 'bottom' && onAttachVideo && mode === 'single' && (
              <button
                onClick={onAttachVideo}
                disabled={isDisabled}
                className="p-2 hover:bg-[var(--surface-elevated)] rounded-xl text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors disabled:opacity-50"
                aria-label="Attach video"
                title="Attach video"
              >
                <Plus className="w-5 h-5" />
              </button>
            )}

            {/* Textarea */}
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder || defaultPlaceholder}
              disabled={isDisabled || isLoading}
              rows={1}
              className="flex-1 resize-none bg-transparent border-0 focus:ring-0 focus:outline-none text-[var(--foreground)] placeholder-[var(--text-tertiary)] text-[15px] leading-6 py-2 px-1 disabled:opacity-50"
              style={{ minHeight: '24px', maxHeight: '120px' }}
            />

            {/* Unified Send / Stop Button */}
            <motion.button
              whileTap={{ scale: 0.92 }}
              transition={{ duration: 0.1 }}
              onClick={() => {
                if (isLoading && onCancel) {
                  onCancel();
                } else if (canSend) {
                  onSend();
                }
              }}
              disabled={!isLoading && !canSend}
              aria-label={isLoading ? 'Stop response' : 'Send message'}
              className={`p-3 rounded-xl transition-all ${
                isLoading
                  ? 'bg-[var(--foreground)] text-[var(--surface)] hover:opacity-80'
                  : canSend
                    ? 'bg-gradient-to-r from-violet-500 to-violet-600 hover:from-violet-600 hover:to-violet-700 text-white shadow-lg shadow-violet-500/30'
                    : 'bg-[var(--surface-elevated)] text-[var(--text-tertiary)]'
              }`}
            >
              <AnimatePresence mode="wait" initial={false}>
                {isLoading ? (
                  <motion.div
                    key="stop"
                    initial={{ scale: 0.5, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.5, opacity: 0 }}
                    transition={{ duration: 0.15 }}
                  >
                    <Square className="w-4 h-4" />
                  </motion.div>
                ) : (
                  <motion.div
                    key="send"
                    initial={{ scale: 0.5, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.5, opacity: 0 }}
                    transition={{ duration: 0.15 }}
                  >
                    <Send className="w-4 h-4" />
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.button>
          </div>
        </div>

        {/* Hint */}
        {variant === 'bottom' && (
          <p className="text-xs text-[var(--text-tertiary)] text-center mt-2">{hintText}</p>
        )}
      </div>
    </div>
  );
}
