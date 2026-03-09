'use client';

import React from 'react';
import { Sparkles, ChevronDown, Check } from 'lucide-react';
import type { SubtitleStyle } from '@/lib/api';

interface SubtitleStyleSelectorProps {
  styles: SubtitleStyle[];
  selectedStyle: string;
  showDropdown: boolean;
  onToggleDropdown: () => void;
  onStyleChange: (styleId: string) => void;
}

/**
 * Dropdown selector for subtitle styles (Hormozi, MrBeast, Minimal, etc.).
 */
export function SubtitleStyleSelector({
  styles,
  selectedStyle,
  showDropdown,
  onToggleDropdown,
  onStyleChange,
}: SubtitleStyleSelectorProps) {
  return (
    <div className="relative">
      <button
        onClick={onToggleDropdown}
        className="flex items-center gap-2 px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
      >
        <Sparkles className="w-3.5 h-3.5 text-amber-500" />
        <span className="capitalize">{selectedStyle}</span>
        <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
      </button>

      {showDropdown && (
        <div className="absolute right-0 top-full mt-1 w-64 bg-white border border-gray-200 rounded-lg shadow-lg z-20">
          {styles.map((style) => (
            <button
              key={style.id}
              onClick={() => onStyleChange(style.id)}
              className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg ${
                style.id === selectedStyle ? 'bg-indigo-50' : ''
              }`}
            >
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-900">{style.name}</p>
                <p className="text-xs text-gray-500">{style.description}</p>
              </div>
              {style.id === selectedStyle && (
                <Check className="w-4 h-4 text-indigo-600" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
