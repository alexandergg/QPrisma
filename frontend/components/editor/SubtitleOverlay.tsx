'use client';

import React, { useMemo, useState } from 'react';

/**
 * Subtitle cue with word-level timing
 */
export interface SubtitleCue {
  id: number;
  start: number;
  end: number;
  text: string;
  words: SubtitleWord[];
}

export interface SubtitleWord {
  word: string;
  start: number;
  end: number;
  edited?: boolean;
  estimated?: boolean;
}

/**
 * Subtitle data structure from backend
 */
export interface SubtitleData {
  version?: string;
  style: string;
  style_config?: SubtitleStyleConfig;
  clip_duration: number;
  text: string;
  word_count: number;
  cues: SubtitleCue[];
  words: SubtitleWord[];
}

/**
 * CSS style configuration for subtitle rendering
 */
export interface SubtitleStyleConfig {
  css?: {
    fontFamily?: string;
    fontSize?: string;
    fontWeight?: string;
    textTransform?: string;
    color?: string;
    highlightColor?: string;
    activeColor?: string;
    backgroundColor?: string;
    textShadow?: string;
    position?: string;
    animation?: string;
    maxWordsPerLine?: number;
    lineHeight?: string;
    padding?: string;
    borderRadius?: string;
    borderLeft?: string;
  };
}

interface SubtitleOverlayProps {
  /** Current playback time relative to clip start (in seconds) */
  currentTime: number;
  /** Subtitle data for the clip */
  subtitleData?: SubtitleData;
  /** Whether subtitles are enabled */
  enabled?: boolean;
  /** Callback when a cue is clicked for editing */
  onCueClick?: (cue: SubtitleCue) => void;
  /** Whether edit mode is enabled */
  editMode?: boolean;
}

/**
 * SubtitleOverlay component renders animated subtitles over video
 * 
 * Supports different animation styles:
 * - word_by_word: Shows words one at a time (Hormozi style)
 * - pop: Words pop in with scale animation (MrBeast style)
 * - fade: Smooth fade in/out (Minimal style)
 * - karaoke: Shows all words, highlights current (Karaoke style)
 * - slide: Slides in from side (News style)
 */
export default function SubtitleOverlay({
  currentTime,
  subtitleData,
  enabled = true,
  onCueClick,
  editMode = false,
}: SubtitleOverlayProps) {
  const [hoveredCue, setHoveredCue] = useState<number | null>(null);

  // Find the active cue based on current time
  const activeCue = useMemo(() => {
    if (!subtitleData?.cues) return null;
    return subtitleData.cues.find(
      (cue) => currentTime >= cue.start && currentTime <= cue.end
    );
  }, [subtitleData, currentTime]);

  // Find the active word within the cue (for karaoke style)
  const activeWordIndex = useMemo(() => {
    if (!activeCue?.words) return -1;
    return activeCue.words.findIndex(
      (word) => currentTime >= word.start && currentTime <= word.end
    );
  }, [activeCue, currentTime]);

  if (!enabled || !subtitleData || !activeCue) {
    return null;
  }

  const styleConfig = subtitleData.style_config?.css || {};
  const animation = styleConfig.animation || 'fade';
  const position = styleConfig.position || 'bottom';

  // Get position classes
  const getPositionClasses = () => {
    switch (position) {
      case 'top':
        return 'top-8 left-1/2 -translate-x-1/2';
      case 'center':
        return 'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2';
      case 'bottom-left':
        return 'bottom-8 left-8';
      case 'bottom-right':
        return 'bottom-8 right-8';
      case 'bottom':
      case 'bottom-center':
      default:
        return 'bottom-12 left-1/2 -translate-x-1/2';
    }
  };

  // Get animation classes based on style
  const getAnimationClasses = () => {
    switch (animation) {
      case 'pop':
        return 'animate-pop';
      case 'slide':
        return 'animate-slide-in';
      case 'karaoke':
      case 'word_by_word':
      case 'fade':
      default:
        return 'animate-fade-in';
    }
  };

  // Build inline styles from config
  const getInlineStyles = (): React.CSSProperties => {
    return {
      fontFamily: styleConfig.fontFamily || "'Inter', sans-serif",
      fontSize: styleConfig.fontSize || '24px',
      fontWeight: styleConfig.fontWeight || '600',
      textTransform: styleConfig.textTransform as React.CSSProperties['textTransform'] || 'none',
      color: styleConfig.color || '#FFFFFF',
      backgroundColor: styleConfig.backgroundColor || 'transparent',
      textShadow: styleConfig.textShadow || '2px 2px 4px rgba(0,0,0,0.8)',
      lineHeight: styleConfig.lineHeight || '1.4',
      padding: styleConfig.padding,
      borderRadius: styleConfig.borderRadius,
      borderLeft: styleConfig.borderLeft,
    };
  };

  // Render words with highlighting for karaoke style
  const renderKaraokeWords = () => {
    if (!activeCue.words) {
      return <span>{activeCue.text}</span>;
    }

    return activeCue.words.map((word, idx) => {
      const isActive = idx === activeWordIndex;
      const isPast = idx < activeWordIndex;
      
      return (
        <span
          key={idx}
          className={`transition-all duration-100 ${
            isActive 
              ? 'scale-110' 
              : ''
          }`}
          style={{
            color: isActive 
              ? (styleConfig.activeColor || styleConfig.highlightColor || '#00BFFF')
              : isPast
                ? (styleConfig.color || '#FFFFFF')
                : (styleConfig.color ? `${styleConfig.color}80` : 'rgba(255,255,255,0.5)'),
            fontWeight: isActive ? '700' : styleConfig.fontWeight || '600',
          }}
        >
          {word.word}{' '}
        </span>
      );
    });
  };

  // Render word-by-word style (shows words progressively)
  const renderWordByWord = () => {
    if (!activeCue.words) {
      return <span>{activeCue.text}</span>;
    }

    // Show all words up to current time
    const visibleWords = activeCue.words.filter((word) => currentTime >= word.start);
    
    return visibleWords.map((word, idx) => {
      const isLatest = idx === visibleWords.length - 1;
      // Alternate colors for Hormozi style
      const useHighlight = idx % 2 === 1;
      
      return (
        <span
          key={idx}
          className={`inline-block ${isLatest ? 'animate-word-pop' : ''}`}
          style={{
            color: useHighlight 
              ? (styleConfig.highlightColor || '#FFD700')
              : (styleConfig.color || '#FFFFFF'),
          }}
        >
          {word.word}{' '}
        </span>
      );
    });
  };

  // Render based on animation style
  const renderSubtitleContent = () => {
    switch (animation) {
      case 'karaoke':
        return renderKaraokeWords();
      case 'word_by_word':
        return renderWordByWord();
      case 'pop':
      case 'slide':
      case 'fade':
      default:
        return <span>{activeCue.text}</span>;
    }
  };

  return (
    <>
      {/* CSS for animations */}
      <style jsx global>{`
        @keyframes fade-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes pop {
          0% { transform: scale(0.8); opacity: 0; }
          50% { transform: scale(1.05); }
          100% { transform: scale(1); opacity: 1; }
        }
        @keyframes slide-in {
          from { transform: translateX(-20px); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        @keyframes word-pop {
          0% { transform: scale(0.9); opacity: 0.5; }
          100% { transform: scale(1); opacity: 1; }
        }
        .animate-fade-in { animation: fade-in 0.2s ease-out; }
        .animate-pop { animation: pop 0.3s ease-out; }
        .animate-slide-in { animation: slide-in 0.3s ease-out; }
        .animate-word-pop { animation: word-pop 0.15s ease-out; }
      `}</style>

      {/* Subtitle container */}
      <div
        className={`absolute ${getPositionClasses()} max-w-[90%] text-center z-30 pointer-events-none`}
        key={activeCue.id} // Re-trigger animation on cue change
      >
        <div
          className={`inline-block ${getAnimationClasses()} ${
            editMode ? 'pointer-events-auto cursor-pointer hover:ring-2 hover:ring-indigo-400 hover:ring-offset-2 rounded' : ''
          } ${hoveredCue === activeCue.id ? 'ring-2 ring-indigo-400 ring-offset-2' : ''}`}
          style={getInlineStyles()}
          onClick={() => editMode && onCueClick?.(activeCue)}
          onMouseEnter={() => editMode && setHoveredCue(activeCue.id)}
          onMouseLeave={() => setHoveredCue(null)}
        >
          {renderSubtitleContent()}
        </div>
      </div>
    </>
  );
}
