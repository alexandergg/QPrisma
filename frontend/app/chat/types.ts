export type { Scene, Chapter, TranscriptSegment } from '@/types';
import type { Scene, Chapter, TranscriptSegment } from '@/types';

export interface VideoData {
  id: string;
  url?: string;
  title?: string;
  duration?: number;
  scenes?: Scene[];
  chapters?: Chapter[];
  transcript?: TranscriptSegment[];
}

export interface LibraryVideo {
  id: string;
  original_filename: string;
  blob_url?: string;
}

export interface UploadingVideo {
  id: string;
  fileName: string;
  fileSize: number;
  mediaId?: string;
  jobId?: string;
  status: 'uploading' | 'processing' | 'completed' | 'error';
  progress?: number;
  uploadSpeed?: string;
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}
