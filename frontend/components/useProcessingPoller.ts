'use client';

import { useCallback } from 'react';
import { API_URL } from '@/lib/config';

export interface UploadedVideo {
  media_id: string;
  blob_name: string;
  job_id?: string;
  media_type: string;
  file_size: number;
  original_filename: string;
  status: 'uploading' | 'processing' | 'completed' | 'error';
  progress?: number;
  error_message?: string;
  frames_analyzed?: number;
  processing_time?: number;
  upload_speed?: string;
  eta?: string;
}

type SetUploadedVideos = React.Dispatch<React.SetStateAction<UploadedVideo[]>>;

/**
 * Hook that returns a polling callback for checking media processing status.
 *
 * Polls `GET /media/<mediaId>/status` every 3 seconds up to 300 attempts
 * (~15 min). Updates the video entry in state when processing completes,
 * fails, or times out.
 */
export function useProcessingPoller(
  setUploadedVideos: SetUploadedVideos,
  onVideoProcessed?: (mediaId: string) => void,
) {
  return useCallback(
    async (mediaId: string, _jobId?: string) => {
      void _jobId;
      let attempts = 0;
      const maxAttempts = 300;

      const pollInterval = setInterval(async () => {
        attempts++;
        if (attempts > maxAttempts) {
          clearInterval(pollInterval);
          setUploadedVideos((prev) =>
            prev.map((v) =>
              v.media_id === mediaId
                ? { ...v, status: 'error' as const, error_message: 'Processing timeout' }
                : v,
            ),
          );
          return;
        }

        try {
          const token = localStorage.getItem('auth_token');
          const response = await fetch(`${API_URL}/media/${mediaId}/status`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          });

          if (!response.ok) {
            console.error('Media status polling failed with status:', response.status);
            return;
          }

          const data = await response.json();
          const status = data?.processing_status as string | undefined;

          setUploadedVideos((prev) =>
            prev.map((v) =>
              v.media_id === mediaId
                ? {
                    ...v,
                    progress:
                      typeof data?.processing_progress === 'number'
                        ? data.processing_progress
                        : v.progress,
                    frames_analyzed:
                      typeof data?.frames_analyzed === 'number'
                        ? data.frames_analyzed
                        : v.frames_analyzed,
                  }
                : v,
            ),
          );

          if (status === 'completed' || data?.processed === true) {
            clearInterval(pollInterval);
            setUploadedVideos((prev) =>
              prev.map((v) =>
                v.media_id === mediaId
                  ? { ...v, status: 'completed' as const, progress: 100 }
                  : v,
              ),
            );
            onVideoProcessed?.(mediaId);
          } else if (status === 'failed') {
            clearInterval(pollInterval);
            setUploadedVideos((prev) =>
              prev.map((v) =>
                v.media_id === mediaId
                  ? {
                      ...v,
                      status: 'error' as const,
                      error_message: data?.processing_message || 'Processing failed',
                    }
                  : v,
              ),
            );
          }
        } catch (error) {
          console.error('Polling error:', error);
        }
      }, 3000);
    },
    [setUploadedVideos, onVideoProcessed],
  );
}

/** Format bytes into a human-readable string (e.g. "12.5 MB"). */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

/** Format seconds into a compact duration (e.g. "2m 30s"). */
export function formatEta(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs}s`;
}
