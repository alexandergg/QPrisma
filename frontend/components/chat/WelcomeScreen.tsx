'use client';

import React, { memo } from 'react';
import { Sparkles, Upload, Library, MessageSquare, ArrowRight } from 'lucide-react';

interface QuickSuggestion {
  text: string;
  icon?: React.ReactNode;
}

interface WelcomeScreenProps {
  onUploadVideo?: () => void;
  onBrowseLibrary?: () => void;
  onQuickSuggestion?: (suggestion: string) => void;
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

function WelcomeScreen({
  onUploadVideo,
  onBrowseLibrary,
  onQuickSuggestion,
  mode = 'single',
  userName,
}: WelcomeScreenProps) {
  const suggestions = mode === 'single' ? SINGLE_VIDEO_SUGGESTIONS : LIBRARY_SUGGESTIONS;
  const greeting = userName ? `Welcome back, ${userName.split(' ')[0]}!` : 'Welcome to QPrisma';

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-4 md:p-8 overflow-y-auto">
      <div className="max-w-2xl w-full text-center">
        {/* Logo/Icon */}
        <div className="w-16 h-16 md:w-20 md:h-20 mx-auto mb-6 md:mb-8 bg-gradient-to-br from-amber-9 to-amber-10 rounded-[var(--radius-2xl)] flex items-center justify-center shadow-[var(--shadow-xl)]">
          <Sparkles className="w-10 h-10 text-white" />
        </div>

        {/* Greeting */}
        <h1 className="text-2xl md:text-4xl font-bold text-[var(--foreground)] mb-3">{greeting}</h1>
        <p className="text-base md:text-lg text-[var(--sage-8)] mb-6 md:mb-10">
          {mode === 'single'
            ? 'Unlock intelligent insights from your videos'
            : 'Search and analyze across your entire video library'}
        </p>

        {/* Action Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 md:gap-4 mb-6 md:mb-10">
          {/* Upload Video Card */}
          <button
            onClick={onUploadVideo}
            className="group bg-[var(--surface)] rounded-[var(--radius-2xl)] p-4 md:p-6 border-2 border-dashed border-[var(--sage-4)] hover:border-amber-5 hover:bg-amber-1 transition-all text-left"
          >
            <div className="w-12 h-12 bg-gradient-to-br from-amber-3 to-amber-4 rounded-[var(--radius-xl)] flex items-center justify-center mb-3 md:mb-4 group-hover:from-amber-4 group-hover:to-amber-5 transition-colors">
              <Upload className="w-6 h-6 text-amber-10" />
            </div>
            <h3 className="text-base md:text-lg font-semibold text-[var(--foreground)] mb-1">Upload Video</h3>
            <p className="text-sm text-[var(--sage-8)]">
              Drag and drop or click to upload a new video for analysis
            </p>
          </button>

          {/* Browse Library Card */}
          <button
            onClick={onBrowseLibrary}
            className="group bg-[var(--surface)] rounded-[var(--radius-2xl)] p-4 md:p-6 border-2 border-dashed border-[var(--sage-4)] hover:border-amber-6 hover:bg-amber-2/50 transition-all text-left"
          >
            <div className="w-12 h-12 bg-gradient-to-br from-amber-4 to-amber-5 rounded-[var(--radius-xl)] flex items-center justify-center mb-3 md:mb-4 group-hover:from-amber-5 group-hover:to-amber-6 transition-colors">
              <Library className="w-6 h-6 text-amber-11" />
            </div>
            <h3 className="text-base md:text-lg font-semibold text-[var(--foreground)] mb-1">Video Library</h3>
            <p className="text-sm text-[var(--sage-8)]">
              Browse and select from your processed videos
            </p>
          </button>
        </div>

        {/* Divider */}
        <div className="flex items-center gap-4 mb-8">
          <div className="flex-1 h-px bg-[var(--sage-4)]"></div>
          <span className="text-sm text-[var(--sage-7)] font-medium">or try a quick prompt</span>
          <div className="flex-1 h-px bg-[var(--sage-4)]"></div>
        </div>

        {/* Quick Suggestions */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 md:gap-3">
          {suggestions.map((suggestion, index) => (
            <button
              key={index}
              onClick={() => onQuickSuggestion?.(suggestion.text)}
              className="group flex items-center gap-3 p-3 md:p-4 bg-[var(--surface)] rounded-[var(--radius-xl)] border border-[var(--sage-3)] hover:border-amber-4 hover:bg-amber-1 transition-all text-left"
            >
              <MessageSquare className="w-5 h-5 text-[var(--sage-7)] group-hover:text-amber-9 flex-shrink-0" />
              <span className="text-sm text-[var(--sage-9)] group-hover:text-[var(--foreground)] flex-1">
                {suggestion.text}
              </span>
              <ArrowRight className="w-4 h-4 text-[var(--sage-5)] group-hover:text-amber-9 opacity-0 group-hover:opacity-100 transition-all" />
            </button>
          ))}
        </div>

        {/* Footer hint */}
        <p className="text-xs text-[var(--sage-7)] mt-4 md:mt-8">
          {mode === 'single'
            ? 'Select a video to start chatting about its content'
            : 'Your questions will search across all your processed videos'}
        </p>
      </div>
    </div>
  );
}

export default memo(WelcomeScreen);
