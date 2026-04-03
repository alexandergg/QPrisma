'use client';

import React, { memo } from 'react';
import { motion } from 'framer-motion';
import { Sparkles, Upload, Library, MessageSquare, ArrowRight } from 'lucide-react';
import { fadeIn, staggerContainer, staggerItem } from '@/lib/animations';

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
    <div className="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto">
      <div className="max-w-2xl w-full text-center">
        {/* Logo/Icon */}
        <motion.div
          variants={fadeIn}
          initial="initial"
          animate="animate"
          className="w-20 h-20 mx-auto mb-8 bg-gradient-to-br from-amber-500 to-orange-600 rounded-2xl flex items-center justify-center shadow-2xl shadow-amber-500/30"
        >
          <Sparkles className="w-10 h-10 text-white" />
        </motion.div>

        {/* Greeting */}
        <motion.h1
          variants={fadeIn}
          initial="initial"
          animate="animate"
          className="text-4xl font-bold text-gray-900 mb-3"
        >
          {greeting}
        </motion.h1>
        <motion.p
          variants={fadeIn}
          initial="initial"
          animate="animate"
          className="text-lg text-gray-500 mb-10"
        >
          {mode === 'single'
            ? 'Unlock intelligent insights from your videos'
            : 'Search and analyze across your entire video library'}
        </motion.p>

        {/* Action Cards */}
        <div className="grid grid-cols-2 gap-4 mb-10">
          {/* Upload Video Card */}
          <button
            onClick={onUploadVideo}
            className="group bg-white rounded-2xl p-6 border-2 border-dashed border-gray-200 hover:border-amber-300 hover:bg-amber-50/50 transition-all text-left"
          >
            <div className="w-12 h-12 bg-gradient-to-br from-amber-100 to-orange-100 rounded-xl flex items-center justify-center mb-4 group-hover:from-amber-200 group-hover:to-orange-200 transition-colors">
              <Upload className="w-6 h-6 text-amber-600" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900 mb-1">Upload Video</h3>
            <p className="text-sm text-gray-500">
              Drag and drop or click to upload a new video for analysis
            </p>
          </button>

          {/* Browse Library Card */}
          <button
            onClick={onBrowseLibrary}
            className="group bg-white rounded-2xl p-6 border-2 border-dashed border-gray-200 hover:border-purple-300 hover:bg-purple-50/50 transition-all text-left"
          >
            <div className="w-12 h-12 bg-gradient-to-br from-purple-100 to-pink-100 rounded-xl flex items-center justify-center mb-4 group-hover:from-purple-200 group-hover:to-pink-200 transition-colors">
              <Library className="w-6 h-6 text-purple-600" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900 mb-1">Video Library</h3>
            <p className="text-sm text-gray-500">
              Browse and select from your processed videos
            </p>
          </button>
        </div>

        {/* Divider */}
        <div className="flex items-center gap-4 mb-8">
          <div className="flex-1 h-px bg-gray-200"></div>
          <span className="text-sm text-gray-400 font-medium">or try a quick prompt</span>
          <div className="flex-1 h-px bg-gray-200"></div>
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
              className="group flex items-center gap-3 p-4 bg-white rounded-xl border border-gray-100 hover:border-amber-200 hover:bg-amber-50/50 transition-colors text-left"
            >
              <MessageSquare className="w-5 h-5 text-gray-400 group-hover:text-amber-600 flex-shrink-0" />
              <span className="text-sm text-gray-600 group-hover:text-gray-900 flex-1">
                {suggestion.text}
              </span>
              <ArrowRight className="w-4 h-4 text-gray-300 group-hover:text-amber-600 opacity-0 group-hover:opacity-100 transition-all" />
            </motion.button>
          ))}
        </motion.div>

        {/* Footer hint */}
        <p className="text-xs text-gray-400 mt-8">
          {mode === 'single'
            ? 'Select a video to start chatting about its content'
            : 'Your questions will search across all your processed videos'}
        </p>
      </div>
    </div>
  );
}

export default memo(WelcomeScreen);
