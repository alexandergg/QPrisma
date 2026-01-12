'use client';

import React, { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, Sparkles } from 'lucide-react';
import { Sidebar } from '@/components/layout';
import { UploadZone, ProcessingCard } from '@/components/upload';
import { apiClient } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';

interface UploadingVideo {
  id: string;
  file: File;
  mediaId?: string;
  jobId?: string;
  status: 'uploading' | 'processing' | 'completed' | 'error';
  error?: string;
}

export default function UploadPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [uploadingVideos, setUploadingVideos] = useState<UploadingVideo[]>([]);
  const [currentMode, setCurrentMode] = useState<'single' | 'library'>('single');

  const handleFilesSelected = useCallback(async (files: File[]) => {
    for (const file of files) {
      const tempId = Math.random().toString(36).substring(7);

      // Add to uploading list
      setUploadingVideos((prev) => [
        {
          id: tempId,
          file,
          status: 'uploading',
        },
        ...prev,
      ]);

      try {
        // Upload with optimized pipeline
        const response = await apiClient.uploadVideoOptimized(file, {
          useSceneDetection: true,
          useHierarchicalSummary: true,
        });

        // Update with real IDs - upload is complete at this point
        setUploadingVideos((prev) =>
          prev.map((v) =>
            v.id === tempId
              ? {
                  ...v,
                  mediaId: response.media_id,
                  jobId: response.job_id,
                  status: 'processing',
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
                  error: 'Upload failed. Please try again.',
                }
              : v
          )
        );
      }
    }
  }, []);

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
          conversations={[]}
          currentMode={currentMode}
          onModeChange={setCurrentMode}
          onNewChat={() => router.push('/chat/new')}
          onSelectConversation={(id) => router.push(`/chat/${id}`)}
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
              isUploading={uploadingVideos.some((v) => v.status === 'uploading')}
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
