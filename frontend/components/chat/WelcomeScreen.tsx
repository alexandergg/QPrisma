'use client';

import React, { memo, useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Sparkles, Upload, Library, MessageSquare, ArrowRight, Play, Clock } from 'lucide-react';
import { fadeIn, staggerContainer, staggerItem } from '@/lib/animations';
import { apiClient, type MediaItem } from '@/lib/api';

interface QuickSuggestion {
  text: string;
  icon?: React.ReactNode;
}

interface WelcomeScreenProps {
  onUploadVideo?: () => void;
  onBrowseLibrary?: () => void;
  onQuickSuggestion?: (suggestion: string) => void;
  onSelectVideoById?: (videoId: string) => void;
  mode?: 'single' | 'library';
  userName?: string;
}

const SINGLE_VIDEO_SUGGESTIONS: QuickSuggestion[] = [
  { text: 'Summarize the main topics of this video' },
  { text: 'What are the key takeaways?' },
  { text: 'Find all mentions of specific topics' },
  { text: 'Generate a timeline of events' },
];

const LIBRARY_SUGGESTIONS: QuickSuggestion[] = [
  { text: 'In which videos do I talk about AI?' },
  { text: 'Find all tutorials across my videos' },
  { text: 'Compare topics between my videos' },
  { text: 'What are my most discussed subjects?' },
];

function formatDuration(seconds?: number): string {
  if (!seconds) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function WelcomeScreen({
  onUploadVideo,
  onBrowseLibrary,
  onQuickSuggestion,
  onSelectVideoById,
  mode = 'single',
  userName,
}: WelcomeScreenProps) {
  const suggestions = mode === 'single' ? SINGLE_VIDEO_SUGGESTIONS : LIBRARY_SUGGESTIONS;
  const greeting = userName ? `Welcome back, ${userName.split(' ')[0]}!` : 'Welcome to QPrisma';

  const [recentVideos, setRecentVideos] = useState<MediaItem[]>([]);

  useEffect(() => {
    apiClient
      .getMedia()
      .then((res) => {
        const sorted = (res.media || [])
          .filter((v) => v.processing_status === 'completed' || v.processed)
          .sort(
            (a, b) =>
              new Date(b.uploaded_at || 0).getTime() -
              new Date(a.uploaded_at || 0).getTime(),
          )
          .slice(0, 4);
        setRecentVideos(sorted);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto">
      <div className="max-w-2xl w-full text-center">
        {/* Logo/Icon */}
        <motion.div
          variants={fadeIn}
          initial="initial"
          animate="animate"
          className="w-20 h-20 mx-auto mb-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-2xl shadow-indigo-500/30"
        >
          <Sparkles className="w-10 h-10 text-white" />
        </motion.div>

        {/* Greeting */}
        <motion.h1
          variants={fadeIn}
          initial="initial"
          animate="animate"
          className="text-4xl font-bold text-[var(--foreground)] mb-3"
        >
          {greeting}
        </motion.h1>
        <motion.p
          variants={fadeIn}
          initial="initial"
          animate="animate"
          className="text-lg text-[var(--text-secondary)] mb-10"
        >
          {mode === 'single'
            ? 'Unlock intelligent insights from your videos'
            : 'Search and analyze across your entire video library'}
        </motion.p>

        {/* Action Cards */}
        <div className="grid grid-cols-2 gap-4 mb-8">
          <button
            onClick={onUploadVideo}
            className="group bg-[var(--surface)] rounded-2xl p-6 border-2 border-dashed border-[var(--border)] hover:border-[var(--amber-6)] hover:bg-[var(--amber-1)] transition-all text-left"
          >
            <div className="w-12 h-12 bg-gradient-to-br from-amber-100 to-orange-100 dark:from-amber-500/20 dark:to-orange-500/20 rounded-xl flex items-center justify-center mb-4 group-hover:from-amber-200 group-hover:to-orange-200 dark:group-hover:from-amber-500/30 dark:group-hover:to-orange-500/30 transition-colors">
              <Upload className="w-6 h-6 text-[var(--amber-8)]" />
            </div>
            <h3 className="text-lg font-semibold text-[var(--foreground)] mb-1">Upload Video</h3>
            <p className="text-sm text-[var(--text-secondary)]">
              Drag and drop or click to upload a new video for analysis
            </p>
          </button>

          <button
            onClick={onBrowseLibrary}
            className="group bg-[var(--surface)] rounded-2xl p-6 border-2 border-dashed border-[var(--border)] hover:border-purple-400 hover:bg-purple-50/50 dark:hover:bg-purple-500/10 transition-all text-left"
          >
            <div className="w-12 h-12 bg-gradient-to-br from-purple-100 to-pink-100 dark:from-purple-500/20 dark:to-pink-500/20 rounded-xl flex items-center justify-center mb-4 group-hover:from-purple-200 group-hover:to-pink-200 dark:group-hover:from-purple-500/30 dark:group-hover:to-pink-500/30 transition-colors">
              <Library className="w-6 h-6 text-purple-600 dark:text-purple-400" />
            </div>
            <h3 className="text-lg font-semibold text-[var(--foreground)] mb-1">Video Library</h3>
            <p className="text-sm text-[var(--text-secondary)]">
              Browse and select from your processed videos
            </p>
          </button>
        </div>

        {/* Recent Videos Inline Picker */}
        {recentVideos.length > 0 && onSelectVideoById && (
          <motion.div
            variants={staggerContainer}
            initial="initial"
            animate="animate"
            className="mb-8"
          >
            <p className="text-sm font-medium text-[var(--text-secondary)] mb-3">
              Recent videos
            </p>
            <div className="grid grid-cols-2 gap-2">
              {recentVideos.map((video) => (
                <motion.button
                  key={video.id}
                  variants={staggerItem}
                  whileHover={{ y: -2, transition: { duration: 0.2 } }}
                  onClick={() => onSelectVideoById(video.id)}
                  className="group flex items-center gap-3 p-3 bg-[var(--surface)] rounded-xl border border-[var(--border-subtle)] hover:border-indigo-300 dark:hover:border-indigo-500/40 hover:shadow-[var(--shadow-sm)] transition-all text-left"
                >
                  <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-500/20 dark:to-purple-500/20 flex items-center justify-center flex-shrink-0">
                    <Play className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-[var(--foreground)] truncate">
                      {video.original_filename || video.name || 'Untitled'}
                    </p>
                    {video.duration != null && (
                      <p className="text-xs text-[var(--text-tertiary)] flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {formatDuration(video.duration)}
                      </p>
                    )}
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
                </motion.button>
              ))}
            </div>
          </motion.div>
        )}

        {/* Divider */}
        <div className="flex items-center gap-4 mb-8">
          <div className="flex-1 h-px bg-[var(--border)]"></div>
          <span className="text-sm text-[var(--text-tertiary)] font-medium">or try a quick prompt</span>
          <div className="flex-1 h-px bg-[var(--border)]"></div>
        </div>

        {/* Quick Suggestions */}
        <motion.div
          variants={staggerContainer}
          initial="initial"
          animate="animate"
          className="grid grid-cols-2 gap-3"
        >
          {suggestions.map((suggestion, index) => (
            <motion.button
              key={index}
              variants={staggerItem}
              onClick={() => onQuickSuggestion?.(suggestion.text)}
              whileHover={{ y: -2, transition: { duration: 0.2 } }}
              className="group flex items-center gap-3 p-4 bg-[var(--surface)] rounded-xl border border-[var(--border-subtle)] hover:border-[var(--amber-4)] hover:bg-[var(--amber-1)] transition-colors text-left"
            >
              <MessageSquare className="w-5 h-5 text-[var(--text-tertiary)] group-hover:text-[var(--amber-8)] flex-shrink-0" />
              <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--foreground)] flex-1">
                {suggestion.text}
              </span>
              <ArrowRight className="w-4 h-4 text-[var(--border)] group-hover:text-[var(--amber-8)] opacity-0 group-hover:opacity-100 transition-all" />
            </motion.button>
          ))}
        </motion.div>

        {/* Footer hint */}
        <p className="text-xs text-[var(--text-tertiary)] mt-8">
          {mode === 'single'
            ? 'Select a video to start chatting about its content'
            : 'Your questions will search across all your processed videos'}
        </p>
      </div>
    </div>
  );
}

export default memo(WelcomeScreen);
