'use client';

import React, { memo, useMemo } from 'react';
import {
  Film,
  X,
  CheckCircle,
  AlertCircle,
  Sparkles,
  Play,
  Clock3,
  DatabaseZap,
} from 'lucide-react';
import ProcessingStep, { ProcessingStepData, ProcessingStepStatus } from './ProcessingStep';
import { formatFileSize } from '@/lib/utils';
import { useJobProgress, type JobProgressState } from './useJobProgress';

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
  const progress = useJobProgress(
    jobId,
    mediaId,
    initialSteps || DEFAULT_STEPS,
    onComplete,
    onError,
  );
  const {
    steps,
    overallProgress,
    status,
    error,
    estimatedTime,
    processingMessage,
    processingMethod,
    backendStatus,
    lastUpdated,
  } = progress;

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
  const statusCopy = getStatusCopy(status, backendStatus);
  const lastUpdatedCopy = formatLastUpdated(lastUpdated);

  return (
    <div className="bg-[var(--surface)] rounded-2xl border border-[var(--border)] shadow-[var(--shadow-xl)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-4 p-5 border-b border-[var(--border-subtle)]">
        <div
          className={`w-12 h-12 rounded-xl flex items-center justify-center ${
            status === 'completed'
              ? 'bg-[var(--sage-2)] text-[var(--sage-8)]'
              : status === 'error'
              ? 'bg-[var(--rose-3)]/50 text-[var(--rose-8)]'
              : 'bg-[var(--violet-2)] text-[var(--violet-8)]'
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
          <h3 className="font-semibold text-[var(--foreground)] truncate">{fileName}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-[var(--text-secondary)]">
            <span>{formatFileSize(fileSize)}</span>
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${statusCopy.className}`}>
              {statusCopy.icon}
              {statusCopy.label}
            </span>
          </div>
        </div>

        {status === 'processing' && onCancel && (
          <button
            onClick={onCancel}
            className="p-2 hover:bg-[var(--surface-elevated)] rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
            aria-label="Cancel processing"
          >
            <X className="w-5 h-5" />
          </button>
        )}

        {status === 'completed' && onViewVideo && mediaId && (
          <button
            onClick={() => onViewVideo(mediaId)}
            className="px-4 py-2 bg-gradient-to-r from-[var(--violet-7)] to-[var(--violet-9)] hover:from-[var(--violet-8)] hover:to-[var(--violet-10)] text-white rounded-xl font-medium flex items-center gap-2 shadow-lg"
          >
            <Play className="w-4 h-4 fill-white" />
            Start Chatting
          </button>
        )}
      </div>

      {/* Overall Progress */}
      <div className="px-5 py-4 bg-[var(--surface-elevated)]/50">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-[var(--foreground)]">
            {status === 'completed'
              ? 'Processing complete'
              : status === 'error'
              ? 'Processing failed'
              : statusCopy.heading || `Processing ${completedSteps}/${steps.length} steps`}
          </span>
          <span className="text-sm font-mono text-[var(--violet-8)]">{displayProgress}%</span>
        </div>
        <div className="h-2 bg-[var(--border)] rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${
              status === 'completed'
                ? 'bg-[var(--sage-7)]'
                : status === 'error'
                ? 'bg-[var(--rose-7)]'
                : 'bg-gradient-to-r from-[var(--violet-7)] to-[var(--violet-9)]'
            }`}
            style={{ width: `${displayProgress}%` }}
          />
        </div>
        {estimatedTime && status === 'processing' && (
          <p className="text-xs text-[var(--text-tertiary)] mt-2 flex items-center gap-1">
            <Sparkles className="w-3 h-3" />
            {estimatedTime}
          </p>
        )}
        {(processingMessage || processingMethod || lastUpdatedCopy) && (
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--text-secondary)]">
            {processingMessage && (
              <span className="inline-flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-[var(--violet-7)]" />
                {processingMessage}
              </span>
            )}
            {processingMethod && (
              <span className="inline-flex items-center gap-1">
                <DatabaseZap className="w-3 h-3 text-[var(--violet-7)]" />
                {formatProcessingMethod(processingMethod)}
              </span>
            )}
            {lastUpdatedCopy && (
              <span className="inline-flex items-center gap-1">
                <Clock3 className="w-3 h-3 text-[var(--text-tertiary)]" />
                {lastUpdatedCopy}
              </span>
            )}
          </div>
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
          <div className="bg-[var(--rose-3)]/30 border border-[var(--rose-7)]/20 rounded-xl p-4">
            <p className="text-sm text-[var(--rose-8)]">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function getStatusCopy(status: JobProgressState['status'], backendStatus: string | null) {
  if (status === 'completed') {
    return {
      label: 'Completed',
      heading: 'Processing complete',
      icon: <CheckCircle className="w-3 h-3" />,
      className: 'bg-[var(--sage-2)] text-[var(--sage-8)]',
    };
  }

  if (status === 'error') {
    return {
      label: 'Failed',
      heading: 'Processing failed',
      icon: <AlertCircle className="w-3 h-3" />,
      className: 'bg-[var(--rose-3)]/50 text-[var(--rose-8)]',
    };
  }

  if (backendStatus === 'queued' || backendStatus === 'uploaded') {
    return {
      label: 'Queued',
      heading: 'Waiting for Databricks pipeline',
      icon: <Clock3 className="w-3 h-3" />,
      className: 'bg-[var(--violet-2)] text-[var(--violet-8)]',
    };
  }

  return {
    label: 'Running',
    heading: 'Running Databricks pipeline',
    icon: <Sparkles className="w-3 h-3" />,
    className: 'bg-[var(--violet-2)] text-[var(--violet-8)]',
  };
}

function formatProcessingMethod(method: string): string {
  if (method.toLowerCase() === 'databricks') return 'Databricks pipeline';
  if (method.toLowerCase() === 'servicebus') return 'Queued via Service Bus';
  return method.replace(/_/g, ' ');
}

function formatLastUpdated(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return `Updated ${parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

export default memo(ProcessingCard);
