'use client';

import React from 'react';
import {
  Film,
  Sparkles,
  Settings,
  Smartphone,
  Monitor,
  Instagram,
  Youtube,
} from 'lucide-react';
import { ExportPresets, ExportEstimate, PlatformPreset, CropMode } from '@/lib/api';
import { formatTime, formatFileSizeMB as formatFileSize } from '@/lib/utils';

const PLATFORM_ICONS: Record<string, React.ReactNode> = {
  tiktok: <Smartphone className="w-5 h-5" />,
  reels: <Instagram className="w-5 h-5" />,
  shorts: <Film className="w-5 h-5" />,
  youtube: <Youtube className="w-5 h-5" />,
  twitter: <Monitor className="w-5 h-5" />,
};

const PLATFORM_COLORS: Record<string, string> = {
  tiktok: 'bg-black text-white hover:bg-gray-800',
  reels: 'bg-gradient-to-r from-purple-500 to-pink-500 text-white hover:from-purple-600 hover:to-pink-600',
  shorts: 'bg-red-600 text-white hover:bg-red-700',
  youtube: 'bg-red-600 text-white hover:bg-red-700',
  twitter: 'bg-black text-white hover:bg-gray-800',
};

interface ExportSettingsFormProps {
  presets: ExportPresets;
  selectedPlatform: string;
  selectedQuality: string;
  selectedCropMode: string | undefined;
  burnSubtitles: boolean;
  showAdvanced: boolean;
  estimate: ExportEstimate | null;
  totalDuration: number;
  onPlatformChange: (platform: string) => void;
  onQualityChange: (quality: string) => void;
  onCropModeChange: (mode: string) => void;
  onBurnSubtitlesChange: (burn: boolean) => void;
  onShowAdvancedChange: (show: boolean) => void;
}

export function ExportSettingsForm({
  presets,
  selectedPlatform,
  selectedQuality,
  selectedCropMode,
  burnSubtitles,
  showAdvanced,
  estimate,
  totalDuration,
  onPlatformChange,
  onQualityChange,
  onCropModeChange,
  onBurnSubtitlesChange,
  onShowAdvancedChange,
}: ExportSettingsFormProps) {
  return (
    <>
      {/* Platform Selection */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Platform
        </label>
        <div className="grid grid-cols-5 gap-2">
          {Object.entries(presets.platforms).map(([key, platform]) => (
            <button
              key={key}
              onClick={() => onPlatformChange(key)}
              className={`flex flex-col items-center gap-1 p-3 rounded-xl border-2 transition-all ${
                selectedPlatform === key
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className={`p-2 rounded-lg ${
                selectedPlatform === key ? PLATFORM_COLORS[key] : 'bg-gray-100'
              }`}>
                {PLATFORM_ICONS[key] || <Film className="w-5 h-5" />}
              </div>
              <span className="text-xs font-medium">
                {(platform as PlatformPreset).display_name}
              </span>
            </button>
          ))}
        </div>

        {/* Platform info */}
        {presets.platforms[selectedPlatform] && (
          <div className="mt-2 text-xs text-gray-500 flex items-center gap-3">
            <span>{presets.platforms[selectedPlatform].resolution}</span>
            <span>{presets.platforms[selectedPlatform].aspect_ratio}</span>
            {presets.platforms[selectedPlatform].max_duration && (
              <span>Max {presets.platforms[selectedPlatform].max_duration}s</span>
            )}
          </div>
        )}
      </div>

      {/* Quality Selection */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Quality
        </label>
        <div className="grid grid-cols-4 gap-2">
          {Object.entries(presets.qualities).map(([key]) => (
            <button
              key={key}
              onClick={() => onQualityChange(key)}
              className={`p-2 rounded-lg border-2 text-center transition-all ${
                selectedQuality === key
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <span className="text-sm font-medium capitalize">{key}</span>
            </button>
          ))}
        </div>
        {presets.qualities[selectedQuality] && (
          <p className="mt-1 text-xs text-gray-500">
            {presets.qualities[selectedQuality].description}
          </p>
        )}
      </div>

      {/* Estimate */}
      {estimate && (
        <div className="bg-gray-50 rounded-xl p-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-600">Estimated size</span>
            <span className="font-medium">{formatFileSize(estimate.estimated_size_mb)}</span>
          </div>
          <div className="flex items-center justify-between text-sm mt-1">
            <span className="text-gray-600">Duration</span>
            <span className="font-medium">{formatTime(totalDuration)}</span>
          </div>
          <div className="flex items-center justify-between text-sm mt-1">
            <span className="text-gray-600">Output</span>
            <span className="font-medium">{estimate.output_resolution}</span>
          </div>
        </div>
      )}

      {/* Advanced Options */}
      <div>
        <button
          onClick={() => onShowAdvancedChange(!showAdvanced)}
          className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"
        >
          <Settings className="w-4 h-4" />
          Advanced options
        </button>

        {showAdvanced && (
          <div className="mt-3 space-y-3 p-3 bg-gray-50 rounded-xl">
            {/* Crop Mode */}
            {presets.platforms[selectedPlatform]?.aspect_ratio === '9:16' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Crop Mode (for vertical video)
                </label>
                <select
                  value={selectedCropMode || 'center'}
                  onChange={(e) => onCropModeChange(e.target.value)}
                  className="w-full p-2 border rounded-lg text-sm"
                >
                  {presets.crop_modes.map((mode: CropMode) => (
                    <option key={mode.id} value={mode.id}>
                      {mode.name} - {mode.description}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Burn Subtitles */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={burnSubtitles}
                onChange={(e) => onBurnSubtitlesChange(e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-sm text-gray-700">Burn subtitles into video</span>
            </label>

            {/* Face tracking hint */}
            {selectedCropMode === 'face_track' && (
              <div className="flex items-start gap-2 p-2 bg-purple-50 rounded-lg">
                <Sparkles className="w-4 h-4 text-purple-600 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-purple-700">
                  Face tracking will analyze the video and keep faces centered when cropping
                  for vertical format. This may take longer to process.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
