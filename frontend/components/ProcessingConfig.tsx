'use client';

import React from 'react';
import { Zap } from 'lucide-react';
import { ExtractionSettings } from './ProcessingExtractionSettings';
import { VideoFilterSettings } from './ProcessingVideoFilters';

interface ProcessingPreset {
  name: string;
  description?: string;
  fps?: number;
  max_frames?: number;
}

interface ProcessingConfigProps {
  selectedPreset: string;
  onPresetChange: (preset: string) => void;
  presets: ProcessingPreset[];
  onConfigChange?: (config: { maxFrames: number }) => void;
}

export default function ProcessingConfig({
  selectedPreset,
  onPresetChange,
  presets,
  onConfigChange,
}: ProcessingConfigProps) {
  return (
    <div className="p-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column: Extraction Settings */}
        <ExtractionSettings
          selectedPreset={selectedPreset}
          onPresetChange={onPresetChange}
          presets={presets}
          onConfigChange={onConfigChange}
        />

        {/* Right Column: Video Filters */}
        <VideoFilterSettings />
      </div>

      {/* Action Buttons */}
      <div className="mt-6 flex gap-4 justify-end">
        <button className="px-6 py-3 bg-gray-700 hover:bg-gray-600 text-white rounded-lg font-medium transition-colors">
          Resetear
        </button>
        <button className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors flex items-center gap-2">
          <Zap className="w-5 h-5" />
          Aplicar Configuración
        </button>
      </div>
    </div>
  );
}
