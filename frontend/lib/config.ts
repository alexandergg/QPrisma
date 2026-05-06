/**
 * Centralized configuration for the QPrisma frontend
 */

/**
 * API base URL - configured via environment variable
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/**
 * Application configuration
 */
export const config = {
  api: {
    baseUrl: API_URL,
    timeout: 30000,
  },
  upload: {
    maxFileSize: 500 * 1024 * 1024, // 500MB
    allowedTypes: ['video/mp4', 'video/webm', 'video/quicktime', 'video/x-msvideo'],
    allowedExtensions: ['.mp4', '.webm', '.mov', '.avi'],
  },
  processing: {
    defaultPreset: 'balanced',
    defaultMaxFrames: 100,
    pollingInterval: 3000,
    maxPollingAttempts: 300,
  },
  video: {
    seekStep: 5, // seconds
    volumeStep: 0.1,
  },
} as const;

/**
 * Feature flags
 */
export const features = {
  optimizedPipeline: true,
  sceneDetection: true,
  hierarchicalSummary: true,
  chatStreaming: true,
} as const;
