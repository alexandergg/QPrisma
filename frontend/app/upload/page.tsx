'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Sparkles } from 'lucide-react';
import { Sidebar } from '@/components/layout';
import { UploadZone, ProcessingCard } from '@/components/upload';
import { apiClient } from '@/lib/api';
import { ChunkedUploader, shouldUseChunkedUpload, UploadProgress } from '@/lib/chunked-upload';

interface UploadingVideo {
  id: string;
  file: File;
  mediaId?: string;
  jobId?: string;
  status: 'uploading' | 'processing' | 'completed' | 'error';
  error?: string;
  progress?: number;       // 0-100 upload progress
  uploadSpeed?: string;    // e.g. "12.5 MB/s"
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export default function UploadPage() {
  const router = useRouter();
  const [uploadingVideos, setUploadingVideos] = useState<UploadingVideo[]>([]);
  const [currentMode, setCurrentMode] = useState<'single' | 'library'>('single');
  const uploadersRef = useRef<Map<string, ChunkedUploader>>(new Map());

  // Cancel ongoing chunked uploads on unmount
  useEffect(() => {
    const uploaders = uploadersRef.current;
    return () => {
      uploaders.forEach((uploader) => {
        uploader.cancel().catch(() => {});
      });
      uploaders.clear();
    };
  }, []);

  const uploadSingleFile = useCallback(async (tempId: string, file: File) => {
    try {
      let response: { media_id: string; job_id?: string };

      if (shouldUseChunkedUpload(file)) {
        // Large file: use chunked upload with progress tracking
        const uploader = new ChunkedUploader(file, {
          useSceneDetection: true,
          useHierarchicalSummary: true,
          blockSizeMb: 8,
          concurrency: 4,
          onProgress: (progress: UploadProgress) => {
            setUploadingVideos((prev) =>
              prev.map((v) =>
                v.id === tempId
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

        uploadersRef.current.set(tempId, uploader);
        const result = await uploader.upload();
        uploadersRef.current.delete(tempId);

        if (!result.success || !result.mediaId) {
          throw new Error(result.error || 'Chunked upload failed');
        }

        response = {
          media_id: result.mediaId,
          job_id: result.jobId,
        };
      } else {
        // Small file: use standard optimized upload
        response = await apiClient.uploadVideoOptimized(file, {
          useSceneDetection: true,
          useHierarchicalSummary: true,
        });
      }

      // Update with real IDs - upload is complete at this point
      setUploadingVideos((prev) =>
        prev.map((v) =>
          v.id === tempId
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
      setUploadingVideos((prev) =>
        prev.map((v) =>
          v.id === tempId
            ? {
                ...v,
                status: 'error',
                error: error instanceof Error ? error.message : 'Upload failed. Please try again.',
                progress: undefined,
                uploadSpeed: undefined,
              }
            : v
        )
      );
    }
  }, []);

  const handleFilesSelected = useCallback((files: File[]) => {
    // Create entries for all files immediately
    const newEntries = files.map((file) => ({
      id: crypto.randomUUID(),
      file,
      status: 'uploading' as const,
    }));

    setUploadingVideos((prev) => [...newEntries, ...prev]);

    // Upload all files concurrently
    for (const entry of newEntries) {
      uploadSingleFile(entry.id, entry.file).catch(() => {
        // Error already handled inside uploadSingleFile
      });
    }
  }, [uploadSingleFile]);

  const handleVideoComplete = (tempId: string, mediaId: string) => {
    setUploadingVideos((prev) =>
      prev.map((v) =>
        v.id === tempId || v.mediaId === mediaId
          ? { ...v, status: 'completed' }
          : v
      )
    );
  };

  const handleViewVideo = (mediaId: string) => {
    router.push(`/chat/new?videoId=${mediaId}`);
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 overflow-hidden">
      {/* Decorative Elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl"></div>
        <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl"></div>
      </div>

      {/* Sidebar */}
      <div className="relative z-10 flex-shrink-0">
        <Sidebar
          currentMode={currentMode}
          onModeChange={setCurrentMode}
          onNewChat={() => router.push('/chat/new')}
        />
      </div>

      {/* Main Content */}
      <main className="relative z-10 flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto p-8">
          {/* Header */}
          <div className="mb-8">
            <button
              onClick={() => router.back()}
              className="flex items-center gap-2 text-gray-500 hover:text-gray-700 mb-4 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>

            <div className="flex items-center gap-3 mb-2">
              <div className="px-3 py-1.5 bg-indigo-100 text-indigo-700 rounded-full text-xs font-semibold flex items-center gap-1.5">
                <Sparkles className="w-3 h-3" />
                AI-Powered Analysis
              </div>
            </div>
            <h1 className="text-3xl font-bold text-gray-900">Upload Videos</h1>
            <p className="text-gray-500 mt-2">
              Drop your videos to unlock intelligent insights with AI analysis
            </p>
          </div>

          {/* Upload Zone */}
          <div className="mb-8">
            <UploadZone
              onFilesSelected={handleFilesSelected}
              isUploading={false}
            />
          </div>

          {/* Processing Queue */}
          {uploadingVideos.length > 0 && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold text-gray-900">Processing Queue</h2>
              {uploadingVideos.map((video) => (
                <ProcessingCard
                  key={video.id}
                  fileName={video.file.name}
                  fileSize={video.file.size}
                  jobId={video.jobId}
                  mediaId={video.mediaId}
                  uploadProgress={video.progress}
                  uploadSpeed={video.uploadSpeed}
                  onComplete={(mediaId) => handleVideoComplete(video.id, mediaId)}
                  onViewVideo={handleViewVideo}
                />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
