'use client';

import React from 'react';
import { X, Film, Settings2, ChevronDown } from 'lucide-react';
import { UploadZone, ProcessingCard } from '@/components/upload';
import { ChunkedUploader, shouldUseChunkedUpload, UploadProgress } from '@/lib/chunked-upload';
import { apiClient } from '@/lib/api';
import { UPLOAD } from '@/lib/constants';
import type { UploadingVideo } from '../types';
import { formatBytes } from '../types';

interface UploadModalProps {
  isOpen: boolean;
  pendingFiles: File[];
  uploadingVideos: UploadingVideo[];
  uploadPreset: string;
  uploadMaxFrames: number;
  onClose: () => void;
  onFilesSelected: (files: File[]) => void;
  onRemovePendingFile: (index: number) => void;
  onPresetChange: (preset: string) => void;
  onMaxFramesChange: (frames: number) => void;
  onUploadingVideosChange: React.Dispatch<React.SetStateAction<UploadingVideo[]>>;
  onUploadComplete: (mediaId: string) => Promise<void>;
}

export default function UploadModal({
  isOpen,
  pendingFiles,
  uploadingVideos,
  uploadPreset,
  uploadMaxFrames,
  onClose,
  onFilesSelected,
  onRemovePendingFile,
  onPresetChange,
  onMaxFramesChange,
  onUploadingVideosChange,
  onUploadComplete,
}: UploadModalProps) {
  if (!isOpen) return null;

  const handleStartProcessing = () => {
    const entries: UploadingVideo[] = pendingFiles.map((file) => ({
      id: crypto.randomUUID(),
      fileName: file.name,
      fileSize: file.size,
      status: 'uploading' as const,
    }));
    onUploadingVideosChange(entries);

    pendingFiles.forEach((file, idx) => {
      const entry = entries[idx];
      (async () => {
        try {
          let response: { media_id: string; job_id?: string };

          if (shouldUseChunkedUpload(file)) {
            const uploader = new ChunkedUploader(file, {
              preset: uploadPreset,
              maxFrames: uploadMaxFrames,
              useSceneDetection: true,
              useHierarchicalSummary: true,
              blockSizeMb: 8,
              concurrency: 4,
              onProgress: (progress: UploadProgress) => {
                onUploadingVideosChange((prev) =>
                  prev.map((v) =>
                    v.id === entry.id
                      ? {
                          ...v,
                          progress: progress.percent,
                          uploadSpeed: progress.speedBytesPerSecond
                            ? `${formatBytes(progress.speedBytesPerSecond)}/s`
                            : undefined,
                        }
                      : v
                  )
                );
              },
            });
            const result = await uploader.upload();
            if (!result.success || !result.mediaId) {
              throw new Error(result.error || 'Chunked upload failed');
            }
            response = { media_id: result.mediaId, job_id: result.jobId };
          } else {
            response = await apiClient.uploadVideoOptimized(file, {
              preset: uploadPreset,
              maxFrames: uploadMaxFrames,
              useSceneDetection: true,
              useHierarchicalSummary: true,
            });
          }

          onUploadingVideosChange((prev) =>
            prev.map((v) =>
              v.id === entry.id
                ? {
                    ...v,
                    mediaId: response.media_id,
                    jobId: response.job_id,
                    status: 'processing',
                    progress: undefined,
                    uploadSpeed: undefined,
                  }
                : v
            )
          );
        } catch (error) {
          console.error('Upload failed:', error);
          onUploadingVideosChange((prev) =>
            prev.map((v) =>
              v.id === entry.id
                ? {
                    ...v,
                    status: 'error',
                    progress: undefined,
                    uploadSpeed: undefined,
                  }
                : v
            )
          );
        }
      })().catch(() => {});
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-gray-900">
            {pendingFiles.length > 1
              ? `Upload ${pendingFiles.length} Videos`
              : 'Upload Video'}
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-500"
            aria-label="Close upload dialog"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Show ProcessingCards when uploading/processing */}
        {uploadingVideos.length > 0 ? (
          <div className="space-y-4">
            {uploadingVideos.map((video) => (
              <ProcessingCard
                key={video.id}
                fileName={video.fileName}
                fileSize={video.fileSize}
                jobId={video.jobId}
                mediaId={video.mediaId}
                uploadProgress={video.progress}
                uploadSpeed={video.uploadSpeed}
                onComplete={async (mediaId) => {
                  onUploadingVideosChange((prev) =>
                    prev.map((v) =>
                      v.id === video.id || v.mediaId === mediaId
                        ? { ...v, status: 'completed' }
                        : v
                    )
                  );
                  await onUploadComplete(mediaId);
                }}
                onError={(error) => {
                  console.error('Processing failed:', error);
                  onUploadingVideosChange((prev) =>
                    prev.map((v) =>
                      v.id === video.id ? { ...v, status: 'error' } : v
                    )
                  );
                }}
                onViewVideo={async (mediaId) => {
                  onClose();
                  onUploadingVideosChange([]);
                  await onUploadComplete(mediaId);
                }}
              />
            ))}
          </div>
        ) : pendingFiles.length > 0 ? (
          /* Configuration step - files selected, configure before upload */
          <div className="space-y-6">
            {/* Selected files list */}
            <div className="space-y-2">
              <div className="rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-3 text-sm text-indigo-700">
                {pendingFiles.length} of {UPLOAD.MAX_FILES} videos selected
                {' '}({formatBytes(pendingFiles.reduce((sum, file) => sum + file.size, 0))} total).
                Processing options below apply to every selected video.
              </div>
              {pendingFiles.map((file, idx) => (
                <div key={idx} className="bg-indigo-50 rounded-xl p-3 flex items-center gap-3">
                  <div className="w-10 h-10 bg-indigo-100 rounded-lg flex items-center justify-center flex-shrink-0">
                    <Film className="w-5 h-5 text-indigo-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-gray-900 truncate text-sm">{file.name}</p>
                    <p className="text-xs text-gray-500">
                      {(file.size / (1024 * 1024)).toFixed(1)} MB
                    </p>
                  </div>
                  <button
                    onClick={() => onRemovePendingFile(idx)}
                    className="p-1.5 hover:bg-indigo-100 rounded-lg text-indigo-600 flex-shrink-0"
                    aria-label={`Remove ${file.name}`}
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>

            {/* Processing Options */}
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-gray-700">
                <Settings2 className="w-4 h-4 text-indigo-500" />
                Processing Options
                {pendingFiles.length > 1 && (
                  <span className="text-xs text-gray-400 font-normal">(applied to all files)</span>
                )}
              </div>

              {/* Preset Selection */}
              <div>
                <label className="block text-sm font-medium text-gray-600 mb-2">
                  Quality Preset
                </label>
                <div className="relative">
                  <select
                    value={uploadPreset}
                    onChange={(e) => onPresetChange(e.target.value)}
                    className="w-full px-4 py-3 bg-gray-50 text-gray-900 rounded-xl border border-gray-200 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 focus:outline-none appearance-none cursor-pointer"
                  >
                    <option value="fast_preview">⚡ Fast Preview - Quick scan (50 frames)</option>
                    <option value="balanced">⚖️ Balanced - Good coverage (200 frames)</option>
                    <option value="high_quality">🎯 High Quality - Deep analysis (600 frames)</option>
                    <option value="adaptive">✨ Adaptive - Auto-adjust by duration</option>
                    <option value="deep_analysis">🔬 Deep Analysis - Long videos (1000 frames)</option>
                    <option value="ultra_deep">🔭 Ultra Deep - Very long 4+ hrs (2000 frames)</option>
                    <option value="interview_mode">🎙️ Interview - Audio priority (200 frames)</option>
                    <option value="action_mode">🎬 Action - Motion detection (800 frames)</option>
                  </select>
                  <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
              </div>

              {/* Frame Count */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm font-medium text-gray-600">
                    Analysis Depth
                  </label>
                  <span className="text-sm font-semibold text-indigo-600">
                    {uploadMaxFrames} frames
                  </span>
                </div>
                <input
                  type="range"
                  min="50"
                  max="2000"
                  step="50"
                  value={uploadMaxFrames}
                  onChange={(e) => onMaxFramesChange(parseInt(e.target.value))}
                  className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                />
                <div className="flex justify-between text-xs text-gray-400 mt-1">
                  <span>Quick</span>
                  <span>Deep</span>
                </div>
              </div>
            </div>

            {/* Start Processing Button */}
            <button
              onClick={handleStartProcessing}
              className="w-full py-3 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl font-semibold transition-all shadow-lg shadow-indigo-500/30"
            >
              {pendingFiles.length > 1
                ? `Start Processing ${pendingFiles.length} Videos`
                : 'Start Processing'}
            </button>
          </div>
        ) : (
          <UploadZone
            maxFiles={UPLOAD.MAX_FILES}
            onFilesSelected={(files) => {
              if (files.length > 0) {
                onFilesSelected(files);
              }
            }}
          />
        )}
      </div>
    </div>
  );
}
