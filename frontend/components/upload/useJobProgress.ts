'use client';

import { useState, useEffect, useRef } from 'react';
import type { ProcessingStepData, ProcessingStepStatus } from './ProcessingStep';
import { apiClient } from '@/lib/api';
import { ERROR_MESSAGES, TIMING } from '@/lib/constants';

export interface JobProgressState {
  steps: ProcessingStepData[];
  overallProgress: number;
  status: 'processing' | 'completed' | 'error';
  error: string | null;
  estimatedTime: string | null;
  processingMessage: string | null;
  processingMethod: string | null;
  backendStatus: string | null;
  lastUpdated: string | null;
}

const TRANSIENT_POLL_FAILURE_LIMIT = 3;

/**
 * Hook that manages job processing state via persisted media status polling.
 *
 * Polls `GET /media/<mediaId>/status`, which is updated by the Databricks
 * status bridge and remains valid across API replicas.
 */
export function useJobProgress(
  jobId: string | undefined,
  mediaId: string | undefined,
  initialSteps: ProcessingStepData[],
  onComplete?: (mediaId: string) => void,
  onError?: (error: string) => void,
): JobProgressState {
  const [steps, setSteps] = useState<ProcessingStepData[]>(initialSteps);
  const [overallProgress, setOverallProgress] = useState(0);
  const [status, setStatus] = useState<'processing' | 'completed' | 'error'>('processing');
  const [error, setError] = useState<string | null>(null);
  const [estimatedTime, setEstimatedTime] = useState<string | null>(null);
  const [processingMessage, setProcessingMessage] = useState<string | null>(null);
  const [processingMethod, setProcessingMethod] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
  }, [onComplete, onError]);

  useEffect(() => {
    if (!jobId || !mediaId || status === 'completed' || status === 'error') return;

    let cancelled = false;
    let stopped = false;
    let pollAttempts = 0;
    let consecutivePollFailures = 0;

    const stopWithError = (message: string, progress = 0) => {
      if (cancelled || stopped) return;

      stopped = true;
      setStatus('error');
      setError(message);
      setEstimatedTime(null);
      setSteps((prev) => markCurrentStep(prev, progress, 'error', message));
      onErrorRef.current?.(message);
    };

    const updateFromStatus = async () => {
      if (cancelled || stopped) return;

      pollAttempts += 1;
      if (pollAttempts > TIMING.MAX_POLL_ATTEMPTS) {
        stopWithError('Processing status check timed out. Please refresh to check the latest status.');
        return;
      }

      try {
        const data = await apiClient.getMediaStatus(mediaId);
        consecutivePollFailures = 0;
        const processingStatus = String(data?.processing_status || 'processing');
        const progress =
          typeof data?.processing_progress === 'number'
            ? data.processing_progress
            : 0;
        const message =
          typeof data?.processing_message === 'string' ? data.processing_message : undefined;

        if (cancelled || stopped) return;

        setProcessingMessage(message || null);
        setProcessingMethod(
          typeof data?.processing_method === 'string' ? data.processing_method : null,
        );
        setBackendStatus(processingStatus);
        setLastUpdated(typeof data?.last_updated === 'string' ? data.last_updated : null);

        if (processingStatus === 'completed' || data?.processed === true) {
          stopped = true;
          setStatus('completed');
          setOverallProgress(100);
          setEstimatedTime(null);
          setSteps((prev) => markAllSteps(prev, 'completed', message));
          onCompleteRef.current?.(mediaId);
          return;
        }

        if (processingStatus === 'failed' || processingStatus === 'error') {
          stopWithError(message || 'Processing failed', progress);
          return;
        }

        setOverallProgress(progress);
        setSteps((prev) => markCurrentStep(prev, progress, 'in_progress', message));

        if (progress > 0 && progress < 100) {
          const remaining = Math.ceil((100 - progress) / 10);
          setEstimatedTime(`~${remaining} min remaining`);
        }
      } catch (pollError) {
        console.error('[useJobProgress] Polling error:', pollError);
        const pollingErrorMessage = getPollingErrorMessage(pollError);
        if (pollingErrorMessage !== ERROR_MESSAGES.networkError) {
          stopWithError(pollingErrorMessage);
          return;
        }

        consecutivePollFailures += 1;
        if (consecutivePollFailures >= TRANSIENT_POLL_FAILURE_LIMIT) {
          stopWithError(pollingErrorMessage);
        }
      }
    };

    void updateFromStatus();
    const pollInterval = setInterval(updateFromStatus, TIMING.JOB_POLL_INTERVAL);

    return () => {
      cancelled = true;
      clearInterval(pollInterval);
    };
  }, [jobId, mediaId, status]);

  return {
    steps,
    overallProgress,
    status,
    error,
    estimatedTime,
    processingMessage,
    processingMethod,
    backendStatus,
    lastUpdated,
  };
}

function getPollingErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.startsWith('HTTP error ')) {
    const statusCode = Number(error.message.replace('HTTP error ', ''));
    if (Number.isFinite(statusCode)) return getStatusErrorMessage(statusCode);
  }

  return ERROR_MESSAGES.networkError;
}

export function getStatusErrorMessage(statusCode: number): string {
  if (statusCode === 401) return ERROR_MESSAGES.unauthorized;
  if (statusCode === 403) return ERROR_MESSAGES.forbidden;
  if (statusCode === 404) return 'Media status was not found.';
  if (statusCode >= 500) return ERROR_MESSAGES.serverError;

  return `Media status polling failed with status ${statusCode}.`;
}

function markAllSteps(
  steps: ProcessingStepData[],
  status: ProcessingStepStatus,
  details?: string,
): ProcessingStepData[] {
  return steps.map((step) => ({
    ...step,
    status,
    progress: status === 'completed' ? 100 : step.progress,
    details: details || step.details,
    endTime: status === 'completed' ? new Date() : step.endTime,
  }));
}

function markCurrentStep(
  steps: ProcessingStepData[],
  overallProgress: number,
  status: ProcessingStepStatus,
  details?: string,
): ProcessingStepData[] {
  const activeIndex = Math.min(
    steps.length - 1,
    Math.max(1, Math.floor((overallProgress / 100) * steps.length)),
  );

  return steps.map((step, index) => {
    if (index < activeIndex) {
      return {
        ...step,
        status: 'completed' as ProcessingStepStatus,
        progress: 100,
        endTime: step.endTime || new Date(),
      };
    }

    if (index === activeIndex) {
      return {
        ...step,
        status,
        progress: Math.max(step.progress || 0, overallProgress),
        details: details || step.details,
        startTime: step.startTime || new Date(),
      };
    }

    return step;
  });
}
