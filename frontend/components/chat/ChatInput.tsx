'use client';

import React, { useRef, useEffect } from 'react';
import { Send, Plus, Loader2, Film, X, Square } from 'lucide-react';

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
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const scrollHeight = textareaRef.current.scrollHeight;
      const lineHeight = 24; // Approximate line height
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
    : 'Press Enter to send • Shift+Enter for new line';

  return (
    <div className="border-t border-[var(--border-subtle)] bg-[var(--surface)]/80 backdrop-blur-xl">
      <div className="max-w-3xl mx-auto p-4">
        {/* Attached Videos Bar */}
        {attachedVideos.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {attachedVideos.map((video) => (
              <div
                key={video.id}
                className="inline-flex items-center gap-2 px-3 py-1.5 bg-[var(--blue-3)] text-[var(--blue-8)] rounded-full text-sm"
              >
                <Film className="w-3 h-3" />
                <span className="max-w-[150px] truncate">{video.name}</span>
                {onRemoveVideo && (
                  <button
                    onClick={() => onRemoveVideo(video.id)}
                    className="p-0.5 hover:bg-[var(--blue-3)]/80 rounded-full transition-colors"
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
        <div className="relative bg-[var(--surface)] rounded-[var(--radius-xl)] border border-[var(--border)] shadow-[var(--shadow-sm)] focus-within:border-[var(--amber-6)] focus-within:ring-4 focus-within:ring-[var(--amber-3)]/30 transition-all">
          <div className="flex items-end gap-2 p-3">
            {/* Attach Video Button */}
            {onAttachVideo && mode === 'single' && (
              <button
                onClick={onAttachVideo}
                disabled={isDisabled}
                className="p-2 hover:bg-[var(--surface-elevated)] rounded-[var(--radius-lg)] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors disabled:opacity-50"
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
              className="flex-1 resize-none bg-transparent border-0 focus:ring-0 focus:outline-none text-[var(--foreground)] placeholder-[var(--text-tertiary)] text-sm leading-6 py-2 px-1 disabled:opacity-50"
              style={{ minHeight: '24px', maxHeight: '120px' }}
            />

            {/* Send Button */}
            <button
              onClick={onSend}
              disabled={isDisabled || isLoading || !value.trim()}
              aria-label={isLoading ? 'Sending message' : 'Send message'}
              className={`p-3 rounded-[var(--radius-lg)] transition-all ${
                value.trim() && !isDisabled && !isLoading
                  ? 'bg-[var(--amber-8)] hover:bg-[var(--amber-9)] text-white shadow-[var(--shadow-sm)]'
                  : 'bg-[var(--surface-elevated)] text-[var(--text-tertiary)]'
              }`}
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>

            {isLoading && onCancel && (
              <button
                onClick={onCancel}
                className="p-3 rounded-[var(--radius-lg)] bg-[var(--surface-elevated)] text-[var(--text-secondary)] hover:bg-[var(--border)] transition-colors"
                aria-label="Stop response"
                title="Stop response"
              >
                <Square className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* Hint */}
        <p className="text-xs text-[var(--text-tertiary)] text-center mt-2">{hintText}</p>
      </div>
    </div>
  );
}
