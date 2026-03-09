'use client';

import React from 'react';
import {
  Sparkles,
  ChevronRight,
  Zap,
  BarChart3,
  Layers,
  Cpu,
} from 'lucide-react';
import VideoUpload from './VideoUpload';

interface Preset {
  name: string;
  description: string;
}

interface StudioUploadViewProps {
  presets: Preset[];
  selectedPreset: string;
  maxFrames: number;
  useOptimizedPipeline: boolean;
  sceneDetectionEnabled: boolean;
  hierarchicalSummaryEnabled: boolean;
  onPresetChange: (preset: string) => void;
  onMaxFramesChange: (frames: number) => void;
  onOptimizedPipelineChange: (enabled: boolean) => void;
  onSceneDetectionChange: (enabled: boolean) => void;
  onHierarchicalSummaryChange: (enabled: boolean) => void;
  onVideoProcessed: (mediaId: string) => void;
}

export function StudioUploadView({
  presets,
  selectedPreset,
  maxFrames,
  useOptimizedPipeline,
  sceneDetectionEnabled,
  hierarchicalSummaryEnabled,
  onPresetChange,
  onMaxFramesChange,
  onOptimizedPipelineChange,
  onSceneDetectionChange,
  onHierarchicalSummaryChange,
  onVideoProcessed,
}: StudioUploadViewProps) {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto p-12">
        <div className="mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-indigo-100 text-indigo-700 rounded-full text-xs font-semibold mb-4">
            <Sparkles className="w-3 h-3" />
            AI-Powered Analysis
          </div>
          <h2 className="text-4xl font-bold text-gray-900 tracking-tight mb-3">
            Upload Video
          </h2>
          <p className="text-lg text-gray-500">
            Unlock intelligent insights from your video content.
          </p>
        </div>

        <div className="space-y-6">
          {/* Preset Selection */}
          <div className="bg-white rounded-2xl p-6 shadow-xl shadow-gray-200/50 border border-gray-100">
            <label className="block text-sm font-semibold text-gray-700 mb-3">
              Processing Preset
            </label>
            <div className="relative">
              <select
                value={selectedPreset}
                onChange={(e) => onPresetChange(e.target.value)}
                className="w-full px-4 py-3.5 bg-gray-50 text-gray-900 rounded-xl border-2 border-transparent focus:border-indigo-500 focus:bg-white focus:outline-none transition-all appearance-none text-base font-medium cursor-pointer hover:bg-gray-100"
              >
                {presets.map((preset) => (
                  <option key={preset.name} value={preset.name}>
                    {preset.name.replace(/_/g, ' ').toUpperCase()}
                  </option>
                ))}
              </select>
              <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none">
                <ChevronRight className="w-5 h-5 text-gray-400 rotate-90" />
              </div>
            </div>
            <p className="mt-3 text-sm text-gray-500">
              {presets.find(p => p.name === selectedPreset)?.description}
            </p>
          </div>

          {/* Analysis Depth */}
          <div className="bg-white rounded-2xl p-6 shadow-xl shadow-gray-200/50 border border-gray-100">
            <div className="flex items-center justify-between mb-4">
              <label className="flex items-center gap-2 text-sm font-semibold text-gray-700">
                <BarChart3 className="w-4 h-4 text-indigo-500" />
                Analysis Depth
              </label>
              <span className="px-3 py-1 bg-gradient-to-r from-indigo-500 to-purple-500 text-white text-xs font-bold rounded-full shadow-lg shadow-indigo-500/30">
                {maxFrames} Frames
              </span>
            </div>
            <input
              type="range"
              min="10"
              max="2000"
              step="10"
              value={maxFrames}
              onChange={(e) => onMaxFramesChange(parseInt(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-500"
            />
            <div className="flex justify-between text-xs text-gray-400 mt-3 font-medium">
              <span>Quick Scan</span>
              <span>Deep Analysis</span>
            </div>
          </div>

          {/* Optimized Pipeline Toggle */}
          <div className="bg-white rounded-2xl p-6 shadow-xl shadow-gray-200/50 border border-gray-100">
            <div className="flex items-center justify-between mb-4">
              <label className="flex items-center gap-2 text-sm font-semibold text-gray-700">
                <Cpu className="w-4 h-4 text-indigo-500" />
                Processing Mode
              </label>
              <button
                onClick={() => onOptimizedPipelineChange(!useOptimizedPipeline)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  useOptimizedPipeline ? 'bg-gradient-to-r from-indigo-500 to-purple-500' : 'bg-gray-300'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-lg transition-transform ${
                    useOptimizedPipeline ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            <div className={`space-y-3 transition-all ${useOptimizedPipeline ? 'opacity-100' : 'opacity-50 pointer-events-none'}`}>
              <p className="text-xs text-gray-500 mb-4">
                Optimized pipeline uses scene detection and hierarchical summaries for faster processing and better search results.
              </p>

              {/* Scene Detection */}
              <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-indigo-400" />
                  <span className="text-sm font-medium text-gray-700">Scene Detection</span>
                </div>
                <button
                  onClick={() => onSceneDetectionChange(!sceneDetectionEnabled)}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                    sceneDetectionEnabled ? 'bg-indigo-500' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${
                      sceneDetectionEnabled ? 'translate-x-5' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              {/* Hierarchical Summary */}
              <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-purple-400" />
                  <span className="text-sm font-medium text-gray-700">AI Summaries</span>
                </div>
                <button
                  onClick={() => onHierarchicalSummaryChange(!hierarchicalSummaryEnabled)}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                    hierarchicalSummaryEnabled ? 'bg-purple-500' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${
                      hierarchicalSummaryEnabled ? 'translate-x-5' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>
            </div>

            {useOptimizedPipeline && (
              <div className="mt-4 p-3 bg-gradient-to-r from-indigo-50 to-purple-50 rounded-lg border border-indigo-100">
                <div className="flex items-center gap-2 text-xs font-semibold text-indigo-700">
                  <Zap className="w-3 h-3" />
                  5-10x faster processing with scene-based analysis
                </div>
              </div>
            )}
          </div>

          {/* Upload Component */}
          <VideoUpload
            selectedPreset={selectedPreset}
            maxFrames={maxFrames}
            useOptimizedPipeline={useOptimizedPipeline}
            sceneDetectionEnabled={sceneDetectionEnabled}
            hierarchicalSummaryEnabled={hierarchicalSummaryEnabled}
            onVideoProcessed={onVideoProcessed}
          />
        </div>
      </div>
    </div>
  );
}
