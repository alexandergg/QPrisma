'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  X,
  Download,
  Film,
  Loader2,
} from 'lucide-react';
import { apiClient, Clip, ExportPresets, ExportEstimate, ExportResult } from '@/lib/api';
import { ExportResultDisplay } from './ExportResultDisplay';
import { ExportSettingsForm } from './ExportSettingsForm';

interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  clip?: Clip;
  clips?: Clip[];
  projectId: string;
  onExportComplete?: (result: ExportResult | ExportResult[]) => void;
}

type ExportMode = 'single' | 'batch';

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

  const loadPresets = useCallback(async () => {
    try {
      const data = await apiClient.getExportPresets();
      setPresets(data);
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
  }, [selectedPlatform]);

  const updateEstimate = useCallback(async () => {
    try {
      const data = await apiClient.estimateExport(totalDuration, selectedPlatform, selectedQuality);
      setEstimate(data);
    } catch (err) {
      console.error('Failed to get estimate:', err);
    }
  }, [selectedPlatform, selectedQuality, totalDuration]);

  useEffect(() => {
    if (isOpen) {
      loadPresets();
    }
  }, [isOpen, loadPresets]);

  useEffect(() => {
    if (presets && totalDuration > 0) {
      updateEstimate();
    }
  }, [selectedPlatform, selectedQuality, totalDuration, presets, updateEstimate]);

  const handlePlatformChange = (platform: string) => {
    setSelectedPlatform(platform);
    setExportResult(null);
    setError(null);
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
          clip.id, selectedPlatform, selectedQuality, selectedCropMode, burnSubtitles
        );
        setExportResult(result);
        onExportComplete?.(result);
      } else {
        const result = await apiClient.exportClipsBatch(
          projectId, clipsToExport.map(c => c.id),
          selectedPlatform, selectedQuality, selectedCropMode, burnSubtitles
        );
        setExportResult(result.results);
        onExportComplete?.(result.results);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setIsExporting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      <div role="dialog" aria-modal="true" aria-label={`Export ${mode === 'single' ? 'Clip' : `${clipsToExport.length} Clips`}`} className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-2">
            <Download className="w-5 h-5 text-indigo-600" />
            <h2 className="text-lg font-semibold">
              Export {mode === 'single' ? 'Clip' : `${clipsToExport.length} Clips`}
            </h2>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded-full transition-colors" aria-label="Close export dialog">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-6">
          {exportResult && (
            <ExportResultDisplay exportResult={exportResult} estimate={estimate} error={error} />
          )}

          {!exportResult && error && (
            <ExportResultDisplay exportResult={{ success: false, clip_id: '', output_url: '' }} estimate={null} error={error} />
          )}

          {presets && !exportResult && (
            <ExportSettingsForm
              presets={presets}
              selectedPlatform={selectedPlatform}
              selectedQuality={selectedQuality}
              selectedCropMode={selectedCropMode}
              burnSubtitles={burnSubtitles}
              showAdvanced={showAdvanced}
              estimate={estimate}
              totalDuration={totalDuration}
              onPlatformChange={handlePlatformChange}
              onQualityChange={setSelectedQuality}
              onCropModeChange={setSelectedCropMode}
              onBurnSubtitlesChange={setBurnSubtitles}
              onShowAdvancedChange={setShowAdvanced}
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-4 border-t bg-gray-50">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900">
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
