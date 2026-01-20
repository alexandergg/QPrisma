'use client';

import React, { useState, useEffect } from 'react';
import {
  X,
  Download,
  Smartphone,
  Monitor,
  Film,
  Twitter,
  Youtube,
  Instagram,
  Sparkles,
  Settings,
  Loader2,
  CheckCircle,
  AlertCircle,
  ExternalLink,
} from 'lucide-react';
import { apiClient, Clip, ExportPresets, ExportEstimate, ExportResult } from '@/lib/api';

interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  clip?: Clip;
  clips?: Clip[];
  projectId: string;
  onExportComplete?: (result: ExportResult | ExportResult[]) => void;
}

type ExportMode = 'single' | 'batch';

const PLATFORM_ICONS: Record<string, React.ReactNode> = {
  tiktok: <Smartphone className="w-5 h-5" />,
  reels: <Instagram className="w-5 h-5" />,
  shorts: <Youtube className="w-5 h-5" />,
  youtube: <Monitor className="w-5 h-5" />,
  twitter: <Twitter className="w-5 h-5" />,
};

const PLATFORM_COLORS: Record<string, string> = {
  tiktok: 'bg-black text-white hover:bg-gray-800',
  reels: 'bg-gradient-to-r from-purple-500 to-pink-500 text-white hover:from-purple-600 hover:to-pink-600',
  shorts: 'bg-red-600 text-white hover:bg-red-700',
  youtube: 'bg-red-600 text-white hover:bg-red-700',
  twitter: 'bg-black text-white hover:bg-gray-800',
};

export default function ExportModal({
  isOpen,
  onClose,
  clip,
  clips,
  projectId,
  onExportComplete,
}: ExportModalProps) {
  const [presets, setPresets] = useState<ExportPresets | null>(null);
  const [selectedPlatform, setSelectedPlatform] = useState('tiktok');
  const [selectedQuality, setSelectedQuality] = useState('standard');
  const [selectedCropMode, setSelectedCropMode] = useState<string | undefined>(undefined);
  const [burnSubtitles, setBurnSubtitles] = useState(true);
  const [estimate, setEstimate] = useState<ExportEstimate | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [exportResult, setExportResult] = useState<ExportResult | ExportResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const mode: ExportMode = clip ? 'single' : 'batch';
  const clipsToExport = clip ? [clip] : (clips || []);
  const totalDuration = clipsToExport.reduce((sum, c) => sum + (c.end_time - c.start_time), 0);

  // Load presets on mount
  useEffect(() => {
    if (isOpen) {
      loadPresets();
    }
  }, [isOpen]);

  // Update estimate when settings change
  useEffect(() => {
    if (presets && totalDuration > 0) {
      updateEstimate();
    }
  }, [selectedPlatform, selectedQuality, totalDuration, presets]);

  const loadPresets = async () => {
    try {
      const data = await apiClient.getExportPresets();
      setPresets(data);

      // Set default crop mode based on platform
      const platform = data.platforms[selectedPlatform];
      if (platform?.aspect_ratio === '9:16') {
        setSelectedCropMode('center');
      } else {
        setSelectedCropMode(undefined);
      }
    } catch (err) {
      console.error('Failed to load presets:', err);
      setError('Failed to load export options');
    }
  };

  const updateEstimate = async () => {
    try {
      const data = await apiClient.estimateExport(totalDuration, selectedPlatform, selectedQuality);
      setEstimate(data);
    } catch (err) {
      console.error('Failed to get estimate:', err);
    }
  };

  const handlePlatformChange = (platform: string) => {
    setSelectedPlatform(platform);
    setExportResult(null);
    setError(null);

    // Update crop mode based on platform aspect ratio
    if (presets) {
      const platformPreset = presets.platforms[platform];
      if (platformPreset?.aspect_ratio === '9:16') {
        setSelectedCropMode('center');
      } else {
        setSelectedCropMode(undefined);
      }
    }
  };

  const handleExport = async () => {
    setIsExporting(true);
    setError(null);
    setExportResult(null);

    try {
      if (mode === 'single' && clip) {
        const result = await apiClient.exportClip(
          clip.id,
          selectedPlatform,
          selectedQuality,
          selectedCropMode,
          burnSubtitles
        );
        setExportResult(result);
        onExportComplete?.(result);
      } else {
        const result = await apiClient.exportClipsBatch(
          projectId,
          clipsToExport.map(c => c.id),
          selectedPlatform,
          selectedQuality,
          selectedCropMode,
          burnSubtitles
        );
        setExportResult(result.results);
        onExportComplete?.(result.results);
      }
    } catch (err: any) {
      setError(err.message || 'Export failed');
    } finally {
      setIsExporting(false);
    }
  };

  const formatDuration = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const formatFileSize = (mb: number): string => {
    if (mb >= 1000) return `${(mb / 1000).toFixed(1)} GB`;
    return `${mb.toFixed(1)} MB`;
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-2">
            <Download className="w-5 h-5 text-indigo-600" />
            <h2 className="text-lg font-semibold">
              Export {mode === 'single' ? 'Clip' : `${clipsToExport.length} Clips`}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-100 rounded-full transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-6">
          {/* Export result */}
          {exportResult && !Array.isArray(exportResult) && exportResult.success && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-4">
              <div className="flex items-start gap-3">
                <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-medium text-green-900">Export complete!</p>
                  <p className="text-sm text-green-700 mt-1">
                    {estimate && `${formatFileSize(estimate.estimated_size_mb)} exported`}
                  </p>
                  {exportResult.output_url && (
                    <a
                      href={exportResult.output_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 mt-2 text-sm font-medium text-green-700 hover:text-green-800"
                    >
                      <Download className="w-4 h-4" />
                      Download Video
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Batch export results */}
          {exportResult && Array.isArray(exportResult) && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-4">
              <div className="flex items-start gap-3">
                <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-medium text-green-900">
                    Exported {exportResult.filter(r => r.success).length} of {exportResult.length} clips
                  </p>
                  <div className="mt-2 space-y-1 max-h-32 overflow-y-auto">
                    {exportResult.map((r, i) => (
                      <div key={r.clip_id} className="flex items-center justify-between text-sm">
                        <span className="text-green-700">Clip {i + 1}</span>
                        {r.output_url && (
                          <a
                            href={r.output_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-green-600 hover:text-green-800"
                          >
                            <Download className="w-4 h-4" />
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4">
              <div className="flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-red-900">Export failed</p>
                  <p className="text-sm text-red-700 mt-1">{error}</p>
                </div>
              </div>
            </div>
          )}

          {/* Platform Selection */}
          {presets && !exportResult && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Platform
                </label>
                <div className="grid grid-cols-5 gap-2">
                  {Object.entries(presets.platforms).map(([key, platform]) => (
                    <button
                      key={key}
                      onClick={() => handlePlatformChange(key)}
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
                        {platform.display_name}
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
                  {Object.entries(presets.qualities).map(([key, quality]) => (
                    <button
                      key={key}
                      onClick={() => setSelectedQuality(key)}
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
                    <span className="font-medium">{formatDuration(totalDuration)}</span>
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
                  onClick={() => setShowAdvanced(!showAdvanced)}
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
                          onChange={(e) => setSelectedCropMode(e.target.value)}
                          className="w-full p-2 border rounded-lg text-sm"
                        >
                          {presets.crop_modes.map((mode) => (
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
                        onChange={(e) => setBurnSubtitles(e.target.checked)}
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
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-4 border-t bg-gray-50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900"
          >
            {exportResult ? 'Close' : 'Cancel'}
          </button>
          {!exportResult && (
            <button
              onClick={handleExport}
              disabled={isExporting || !presets}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isExporting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Exporting...
                </>
              ) : (
                <>
                  <Download className="w-4 h-4" />
                  Export {mode === 'single' ? 'Clip' : `${clipsToExport.length} Clips`}
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
