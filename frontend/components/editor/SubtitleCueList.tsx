'use client';

import React from 'react';
import {
  Type,
  Pencil,
  X,
  Save,
} from 'lucide-react';
import { SubtitleData, SubtitleCue } from '@/lib/api';
import { formatTimeWithMs as formatTime } from '@/lib/utils';

interface SubtitleCueListProps {
  subtitleData: SubtitleData | undefined;
  activeCue: SubtitleCue | undefined;
  editingCue: number | null;
  editText: string;
  onEditTextChange: (text: string) => void;
  onStartEdit: (cue: SubtitleCue) => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  onSeek?: (time: number) => void;
}

export function SubtitleCueList({
  subtitleData,
  activeCue,
  editingCue,
  editText,
  onEditTextChange,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  onSeek,
}: SubtitleCueListProps) {
  if (!subtitleData) {
    return (
      <div className="px-4 py-8 text-center text-gray-500">
        <Type className="w-8 h-8 mx-auto mb-2 text-gray-300" />
        <p className="text-sm">No subtitles generated yet</p>
        <p className="text-xs text-gray-400 mt-1">
          Click &quot;Generate&quot; to create subtitles from transcription
        </p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-gray-100">
      {subtitleData.cues?.map((cue: SubtitleCue) => {
        const isActive = activeCue?.id === cue.id;
        const isEditing = editingCue === cue.id;

        return (
          <div
            key={cue.id}
            className={`flex items-start gap-3 px-4 py-2 transition-colors ${
              isActive ? 'bg-indigo-50' : 'hover:bg-gray-50'
            }`}
          >
            {/* Time */}
            <button
              onClick={() => onSeek?.(cue.start)}
              className="text-xs text-gray-400 hover:text-indigo-600 font-mono whitespace-nowrap pt-0.5"
            >
              {formatTime(cue.start)}
            </button>

            {/* Text */}
            <div className="flex-1 min-w-0">
              {isEditing ? (
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={editText}
                    onChange={(e) => onEditTextChange(e.target.value)}
                    className="flex-1 px-2 py-1 text-sm border border-indigo-300 rounded focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') onSaveEdit();
                      if (e.key === 'Escape') onCancelEdit();
                    }}
                  />
                  <button
                    onClick={onSaveEdit}
                    className="p-1 text-green-600 hover:bg-green-50 rounded"
                  >
                    <Save className="w-4 h-4" />
                  </button>
                  <button
                    onClick={onCancelEdit}
                    className="p-1 text-gray-400 hover:bg-gray-100 rounded"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ) : (
                <p
                  className={`text-sm ${isActive ? 'text-indigo-900 font-medium' : 'text-gray-700'}`}
                >
                  {cue.text}
                </p>
              )}
            </div>

            {/* Edit button */}
            {!isEditing && (
              <button
                onClick={() => onStartEdit(cue)}
                className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded opacity-0 group-hover:opacity-100"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
