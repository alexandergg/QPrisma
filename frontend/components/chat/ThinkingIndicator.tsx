'use client';

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';

interface ThinkingIndicatorProps {
  startTime?: number | null;
}

export default function ThinkingIndicator({ startTime }: ThinkingIndicatorProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startTime) return;
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.25 }}
      className="flex items-start gap-3"
    >
      {/* Animated avatar */}
      <div className="relative flex-shrink-0">
        <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-violet-500 to-violet-600 flex items-center justify-center shadow-lg shadow-violet-500/20">
          <Sparkles className="w-4 h-4 text-white thinking-sparkle" />
        </div>
        <div className="absolute inset-0 rounded-xl thinking-shimmer" />
      </div>

      {/* Text with animated dots */}
      <div className="flex items-center gap-2.5 pt-1.5">
        <div className="flex gap-1">
          <span
            className="w-1.5 h-1.5 rounded-full bg-[var(--violet-8)] animate-bounce"
            style={{ animationDelay: '0ms' }}
          />
          <span
            className="w-1.5 h-1.5 rounded-full bg-[var(--violet-8)] animate-bounce"
            style={{ animationDelay: '150ms' }}
          />
          <span
            className="w-1.5 h-1.5 rounded-full bg-[var(--violet-8)] animate-bounce"
            style={{ animationDelay: '300ms' }}
          />
        </div>
        <span className="text-sm text-[var(--text-secondary)] font-medium">
          Thinking{elapsed >= 3 ? ` · ${elapsed}s` : ''}
        </span>
      </div>
    </motion.div>
  );
}
