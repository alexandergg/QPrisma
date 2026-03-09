'use client';

import React, { memo, useMemo } from 'react';
import { Film, X, CheckCircle, AlertCircle, Sparkles, Play } from 'lucide-react';
import ProcessingStep, { ProcessingStepData, ProcessingStepStatus } from './ProcessingStep';
import { formatFileSize } from '@/lib/utils';
import { useJobProgress } from './useJobProgress';

interface ProcessingCardProps {
  fileName: string;
  fileSize: number;
  jobId?: string;
  initialSteps?: ProcessingStepData[];
  onComplete?: (mediaId: string) => void;
  onError?: (error: string) => void;
  onViewVideo?: (mediaId: string) => void;
  onCancel?: () => void;
  mediaId?: string;
  uploadProgress?: number;   // 0-100, shown during upload phase
  uploadSpeed?: string;      // e.g. "12.5 MB/s"
}

const DEFAULT_STEPS: ProcessingStepData[] = [
  { id: 'upload', name: 'Uploading to cloud', status: 'pending' },
  { id: 'audio', name: 'Extracting audio', status: 'pending' },
  { id: 'transcribe', name: 'Transcribing speech', status: 'pending' },
  { id: 'frames', name: 'Analyzing visual frames', status: 'pending' },
  { id: 'scenes', name: 'Detecting scenes', status: 'pending' },
  { id: 'graph', name: 'Building knowledge graph', status: 'pending' },
  { id: 'embeddings', name: 'Generating embeddings', status: 'pending' },
];

function ProcessingCard({
  fileName,
  fileSize,
  jobId,
  initialSteps,
  onComplete,
  onError,
  onViewVideo,
  onCancel,
  mediaId,
  uploadProgress,
  uploadSpeed,
}: ProcessingCardProps) {
  const { steps, overallProgress, status, error, estimatedTime, wsConnected } = useJobProgress(
    jobId,
    mediaId,
    initialSteps || DEFAULT_STEPS,
    onComplete,
    onError,
  );
  const jobDebugInfo = jobId ? `Job ID: ${jobId.substring(0, 8)}...` : '';

  const stepsWithUploadStatus = useMemo(() => {
    if (!jobId) {
      // Show upload progress if available
      if (uploadProgress !== undefined) {
        return steps.map((step) =>
          step.id === 'upload'
            ? {
                ...step,
                status: 'in_progress' as ProcessingStepStatus,
                progress: uploadProgress,
                details: uploadSpeed ? `${uploadSpeed}` : undefined,
                startTime: step.startTime || new Date(),
              }
            : step
        );
      }
      return steps;
    }
    return steps.map((step) =>
      step.id === 'upload'
        ? { ...step, status: 'completed' as ProcessingStepStatus, progress: 100, endTime: new Date() }
        : step
    );
  }, [jobId, steps, uploadProgress, uploadSpeed]);

  const displayProgress = jobId
    ? Math.max(overallProgress, 10)
    : uploadProgress !== undefined
      ? Math.round(uploadProgress * (1 / DEFAULT_STEPS.length)) // Upload is 1 of 7 steps
      : overallProgress;

  const completedSteps = steps.filter((s) => s.status === 'completed').length;

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-xl shadow-gray-200/50 overflow-hidden">
      {/* Debug Info (temporary) */}
      {jobDebugInfo && (
        <div className="px-4 py-2 bg-gray-100 text-xs text-gray-500 font-mono">
          {jobDebugInfo} | Progress: {displayProgress}%
        </div>
      )}
      {/* Header */}
      <div className="flex items-center gap-4 p-5 border-b border-gray-100">
        <div
          className={`w-12 h-12 rounded-xl flex items-center justify-center ${
            status === 'completed'
              ? 'bg-green-100 text-green-600'
              : status === 'error'
              ? 'bg-red-100 text-red-600'
              : 'bg-indigo-100 text-indigo-600'
          }`}
        >
          {status === 'completed' ? (
            <CheckCircle className="w-6 h-6" />
          ) : status === 'error' ? (
            <AlertCircle className="w-6 h-6" />
          ) : (
            <Film className="w-6 h-6" />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 truncate">{fileName}</h3>
          <p className="text-sm text-gray-500">{formatFileSize(fileSize)}</p>
        </div>

        {status === 'processing' && onCancel && (
          <button
            onClick={onCancel}
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-colors"
            aria-label="Cancel processing"
          >
            <X className="w-5 h-5" />
          </button>
        )}

        {status === 'completed' && onViewVideo && mediaId && (
          <button
            onClick={() => onViewVideo(mediaId)}
            className="px-4 py-2 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl font-medium flex items-center gap-2 shadow-lg shadow-indigo-500/30"
          >
            <Play className="w-4 h-4 fill-white" />
            Start Chatting
          </button>
        )}
      </div>

      {/* Overall Progress */}
      <div className="px-5 py-4 bg-gray-50/50">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">
            {status === 'completed'
              ? 'Processing complete!'
              : status === 'error'
              ? 'Processing failed'
              : `Processing... ${completedSteps}/${steps.length} steps`}
          </span>
          <span className="text-sm font-mono text-indigo-600">{displayProgress}%</span>
        </div>
        <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${
              status === 'completed'
                ? 'bg-green-500'
                : status === 'error'
                ? 'bg-red-500'
                : 'bg-gradient-to-r from-indigo-500 to-purple-500'
            }`}
            style={{ width: `${displayProgress}%` }}
          />
        </div>
        {estimatedTime && status === 'processing' && (
          <p className="text-xs text-gray-400 mt-2 flex items-center gap-1">
            <Sparkles className="w-3 h-3" />
            {estimatedTime}
          </p>
        )}
      </div>

      {/* Steps */}
      <div className="p-5 space-y-0">
        {stepsWithUploadStatus.map((step, index) => (
          <ProcessingStep
            key={step.id}
            step={step}
            isLast={index === stepsWithUploadStatus.length - 1}
          />
        ))}
      </div>

      {/* Error Message */}
      {status === 'error' && error && (
        <div className="px-5 pb-5">
          <div className="bg-red-50 border border-red-100 rounded-xl p-4">
            <p className="text-sm text-red-600">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(ProcessingCard);
