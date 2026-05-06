'use client';

import { useState, useEffect } from 'react';
import type { ProcessingStepData, ProcessingStepStatus } from './ProcessingStep';

// Map backend stage names to frontend step IDs
const STAGE_TO_STEP: Record<string, string> = {
  // Download/upload stages
  downloading: 'upload',
  started: 'upload',

  // Frame extraction and analysis stages
  extracting: 'frames',
  analyzing: 'frames',
  batch_submit: 'frames',
  batch_wait: 'frames',
  batch_results: 'frames',

  // Transcription stages
  transcribing: 'transcribe',
  audio: 'audio',

  // Scene detection
  scenes: 'scenes',

  // Knowledge graph
  graph: 'graph',

  // Embeddings
  embeddings: 'embeddings',

  // Direct step IDs for compatibility
  upload: 'upload',
  transcribe: 'transcribe',
  frames: 'frames',
};

export interface JobProgressState {
  steps: ProcessingStepData[];
  overallProgress: number;
  status: 'processing' | 'completed' | 'error';
  error: string | null;
  estimatedTime: string | null;
  wsConnected: boolean;
}

/**
 * Hook that manages job processing state via WebSocket with fallback polling.
 *
 * Connects to `ws://<host>/ws/jobs/<jobId>` for real-time progress updates
 * and falls back to polling `GET /media/<mediaId>/status` when the WebSocket
 * is not connected.
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
  const [wsConnected, setWsConnected] = useState(false);

  // ── Fallback polling ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!jobId || status === 'completed' || status === 'error') return;

    const pollInterval = setInterval(async () => {
      if (wsConnected) return; // Skip polling if WebSocket is working

      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
        const token = localStorage.getItem('auth_token');
        const response = await fetch(`${apiUrl}/media/${mediaId}/status`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });

        if (response.ok) {
          const data = await response.json();

          if (data.processing_status === 'completed') {
            setStatus('completed');
            setOverallProgress(100);
            setSteps((prev) =>
              prev.map((step) => ({
                ...step,
                status: 'completed' as ProcessingStepStatus,
                progress: 100,
                endTime: new Date(),
              })),
            );
            onComplete?.(mediaId || '');
            clearInterval(pollInterval);
          } else if (data.processing_status === 'failed') {
            setStatus('error');
            setError(data.error || 'Processing failed');
            clearInterval(pollInterval);
          }
        }
      } catch {
        // Poll error – will retry automatically
      }
    }, 5000);

    return () => clearInterval(pollInterval);
  }, [jobId, mediaId, status, wsConnected, onComplete]);

  // ── WebSocket connection ─────────────────────────────────────────────────
  useEffect(() => {
    if (!jobId) return;

    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
    const token = localStorage.getItem('auth_token');
    const authQuery = token ? `?token=${encodeURIComponent(token)}` : '';
    const ws = new WebSocket(`${wsUrl}/ws/jobs/${jobId}${authQuery}`);

    ws.onopen = () => {
      setWsConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === 'job_progress') {
          const { progress, stage, message, step_progress } = data.payload;

          // Map backend stage to frontend step ID
          const stepId = STAGE_TO_STEP[stage] || stage;

          setOverallProgress(progress);

          setSteps((prev) =>
            prev.map((step) => {
              if (step.id === stepId) {
                return {
                  ...step,
                  status: 'in_progress' as ProcessingStepStatus,
                  progress: step_progress || progress,
                  details: message,
                  startTime: step.startTime || new Date(),
                };
              }
              // Mark previous steps as completed
              const stageIndex = prev.findIndex((s) => s.id === stepId);
              const stepIndex = prev.findIndex((s) => s.id === step.id);
              if (stepIndex < stageIndex && step.status !== 'completed') {
                return {
                  ...step,
                  status: 'completed' as ProcessingStepStatus,
                  progress: 100,
                  endTime: new Date(),
                };
              }
              return step;
            }),
          );

          if (progress > 0 && progress < 100) {
            const remaining = Math.ceil((100 - progress) / 10);
            setEstimatedTime(`~${remaining} min remaining`);
          }
        }

        if (data.type === 'job_completed') {
          setStatus('completed');
          setOverallProgress(100);
          setSteps((prev) =>
            prev.map((step) => ({
              ...step,
              status: 'completed' as ProcessingStepStatus,
              progress: 100,
              endTime: new Date(),
            })),
          );
          onComplete?.(data.payload?.media_id || mediaId || '');
        }

        if (data.type === 'job_failed') {
          setStatus('error');
          setError(data.payload?.error || 'Processing failed');
          onError?.(data.payload?.error || 'Processing failed');
        }

        // Handle heartbeat / initial status from server
        if (data.type === 'connected' || data.type === 'heartbeat') {
          // Heartbeat received
        }
      } catch (e) {
        console.error('[useJobProgress] WebSocket message parse error:', e);
      }
    };

    ws.onerror = (wsError) => {
      console.error('[useJobProgress] WebSocket error:', wsError);
      setWsConnected(false);
    };

    ws.onclose = () => {
      setWsConnected(false);
    };

    return () => {
      ws.close();
    };
  }, [jobId, mediaId, onComplete, onError]);

  return { steps, overallProgress, status, error, estimatedTime, wsConnected };
}
