'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  Type,
  Sparkles,
  RefreshCw,
  Download,
} from 'lucide-react';
import { apiClient, Clip, SubtitleData, SubtitleCue, SubtitleStyle } from '@/lib/api';
import { SubtitleCueList } from './SubtitleCueList';
import { SubtitleStyleSelector } from './SubtitleStyleSelector';

interface SubtitleEditorProps {
  /** The clip to edit subtitles for */
  clip: Clip;
  /** Callback when subtitles are updated */
  onSubtitlesUpdated?: (clip: Clip) => void;
  /** Current playback time relative to clip start */
  currentTime?: number;
  /** Callback to seek video to a specific time */
  onSeek?: (time: number) => void;
}

/**
 * SubtitleEditor component for managing clip subtitles
 * 
 * Features:
 * - Generate subtitles from transcription
 * - Choose subtitle styles
 * - Edit individual cues inline
 * - Preview current cue
 * - Export SRT
 */
export default function SubtitleEditor({
  clip,
  onSubtitlesUpdated,
  currentTime = 0,
  onSeek,
}: SubtitleEditorProps) {
  const [loading, setLoading] = useState(false);
  const [styles, setStyles] = useState<SubtitleStyle[]>([]);
  const [selectedStyle, setSelectedStyle] = useState(clip.subtitle_style || 'hormozi');
  const [showStyleDropdown, setShowStyleDropdown] = useState(false);
  const [subtitleData, setSubtitleData] = useState<SubtitleData | undefined>(clip.subtitles_data);
  const [editingCue, setEditingCue] = useState<number | null>(null);
  const [editText, setEditText] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Load available styles on mount
  useEffect(() => {
    const loadStyles = async () => {
      try {
        const fetchedStyles = await apiClient.getSubtitleStyles();
        setStyles(fetchedStyles);
      } catch (e) {
        console.error('Failed to load subtitle styles:', e);
        // Fallback styles
        setStyles([
          { id: 'hormozi', name: 'Hormozi', description: 'Word-by-word, bold, yellow/white' },
          { id: 'mrbeast', name: 'MrBeast', description: 'Large, dramatic, all caps' },
          { id: 'minimal', name: 'Minimal', description: 'Small, clean, professional' },
          { id: 'karaoke', name: 'Karaoke', description: 'Highlight current word' },
          { id: 'news', name: 'News', description: 'Lower third, solid background' },
        ]);
      }
    };
    loadStyles();
  }, []);

  // Update local state when clip changes
  useEffect(() => {
    setSubtitleData(clip.subtitles_data);
    setSelectedStyle(clip.subtitle_style || 'hormozi');
  }, [clip]);

  // Find active cue based on current time
  const activeCue = subtitleData?.cues?.find(
    (cue: SubtitleCue) => currentTime >= cue.start && currentTime <= cue.end
  );

  // Generate subtitles from transcription
  const handleGenerate = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const result = await apiClient.generateClipSubtitles(clip.id, selectedStyle);
      
      if (result.success && result.subtitle_data) {
        setSubtitleData(result.subtitle_data);
        // Notify parent
        if (onSubtitlesUpdated) {
          onSubtitlesUpdated({
            ...clip,
            subtitles_enabled: true,
            subtitle_style: selectedStyle,
            subtitles_data: result.subtitle_data,
          });
        }
      } else {
        setError(result.error || 'Failed to generate subtitles');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to generate subtitles');
    } finally {
      setLoading(false);
    }
  }, [clip, selectedStyle, onSubtitlesUpdated]);

  // Change style (regenerate cues with new grouping)
  const handleStyleChange = useCallback(async (styleId: string) => {
    setSelectedStyle(styleId);
    setShowStyleDropdown(false);
    
    if (subtitleData) {
      // Regenerate with new style
      setLoading(true);
      try {
        const result = await apiClient.generateClipSubtitles(clip.id, styleId);
        if (result.success && result.subtitle_data) {
          setSubtitleData(result.subtitle_data);
          if (onSubtitlesUpdated) {
            onSubtitlesUpdated({
              ...clip,
              subtitle_style: styleId,
              subtitles_data: result.subtitle_data,
            });
          }
        }
      } catch (e) {
        console.error('Failed to change style:', e);
      } finally {
        setLoading(false);
      }
    }
  }, [clip, subtitleData, onSubtitlesUpdated]);

  // Start editing a cue
  const handleStartEdit = (cue: SubtitleCue) => {
    setEditingCue(cue.id);
    setEditText(cue.text);
  };

  // Save cue edit
  const handleSaveEdit = async () => {
    if (editingCue === null) return;
    
    try {
      await apiClient.updateSubtitleCue(clip.id, editingCue, editText);
      
      // Update local state
      if (subtitleData) {
        const updatedCues = subtitleData.cues.map((cue: SubtitleCue) =>
          cue.id === editingCue ? { ...cue, text: editText } : cue
        );
        const updatedData = {
          ...subtitleData,
          cues: updatedCues,
          text: updatedCues.map((c: SubtitleCue) => c.text).join(' '),
        };
        setSubtitleData(updatedData);
        
        if (onSubtitlesUpdated) {
          onSubtitlesUpdated({
            ...clip,
            subtitles_data: updatedData,
          });
        }
      }
      
      setEditingCue(null);
      setEditText('');
    } catch (e) {
      console.error('Failed to save cue:', e);
    }
  };

  // Export SRT
  const handleExportSRT = async () => {
    try {
      const srtContent = await apiClient.exportSubtitlesSRT(clip.id);
      
      // Download as file
      const blob = new Blob([srtContent], { type: 'text/srt' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `clip-${clip.id}.srt`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Failed to export SRT:', e);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Type className="w-4 h-4 text-gray-500" />
          <h3 className="font-semibold text-gray-900 text-sm">Subtitles</h3>
          {subtitleData && (
            <span className="text-xs text-gray-500">
              ({subtitleData.word_count} words, {subtitleData.cues?.length || 0} cues)
            </span>
          )}
        </div>
        
        <div className="flex items-center gap-2">
          {/* Style Selector */}
          <SubtitleStyleSelector
            styles={styles}
            selectedStyle={selectedStyle}
            showDropdown={showStyleDropdown}
            onToggleDropdown={() => setShowStyleDropdown(!showStyleDropdown)}
            onStyleChange={handleStyleChange}
          />

          {/* Generate Button */}
          <button
            onClick={handleGenerate}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" />
            )}
            {subtitleData ? 'Regenerate' : 'Generate'}
          </button>

          {/* Export SRT */}
          {subtitleData && (
            <button
              onClick={handleExportSRT}
              className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg"
              title="Export SRT"
            >
              <Download className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="px-4 py-2 bg-red-50 text-red-600 text-sm">
          {error}
        </div>
      )}

      {/* Content */}
      <div className="max-h-64 overflow-y-auto">
        <SubtitleCueList
          subtitleData={subtitleData}
          activeCue={activeCue}
          editingCue={editingCue}
          editText={editText}
          onEditTextChange={setEditText}
          onStartEdit={handleStartEdit}
          onSaveEdit={handleSaveEdit}
          onCancelEdit={() => setEditingCue(null)}
          onSeek={onSeek}
        />
      </div>

      {/* Footer with preview */}
      {subtitleData && activeCue && (
        <div className="px-4 py-2 border-t border-gray-100 bg-gray-900 text-white">
          <p className="text-sm font-medium text-center">
            {activeCue.text}
          </p>
        </div>
      )}
    </div>
  );
}
