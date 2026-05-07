'use client';

import React, { useState, useCallback, useRef } from 'react';
import { AlertCircle, Film, CloudUpload } from 'lucide-react';
import { apiClient } from '@/lib/api';
import { ChunkedUploader, shouldUseChunkedUpload, UploadProgress } from '@/lib/chunked-upload';
import { UPLOAD } from '@/lib/constants';
import { UploadStatusCard } from './UploadStatusCard';
import {
  useProcessingPoller,
  formatBytes,
  formatEta,
  type UploadedVideo,
} from './useProcessingPoller';

interface VideoUploadProps {
  selectedPreset: string;
  maxFrames?: number;
  useOptimizedPipeline?: boolean;
  sceneDetectionEnabled?: boolean;
  hierarchicalSummaryEnabled?: boolean;
  onVideoProcessed?: (mediaId: string) => void;
}

export default function VideoUpload({
  selectedPreset,
  maxFrames = 100,
  useOptimizedPipeline = false,
  sceneDetectionEnabled = true,
  hierarchicalSummaryEnabled = true,
  onVideoProcessed
}: VideoUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadedVideos, setUploadedVideos] = useState<UploadedVideo[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const pollProcessingStatus = useProcessingPoller(setUploadedVideos, onVideoProcessed);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(Array.from(e.target.files));
    }
  };

  const handleFiles = useCallback(async (files: File[]) => {
    const acceptedFiles = files.slice(0, UPLOAD.MAX_FILES);
    setUploadError(
      files.length > UPLOAD.MAX_FILES
        ? `You can upload up to ${UPLOAD.MAX_FILES} videos at once. ${acceptedFiles.length} of ${files.length} selected files were added.`
        : null,
    );

    for (const file of acceptedFiles) {
      if (!file.type.startsWith('video/')) {
        setUploadError(`${file.name} is not a supported video file.`);
        continue;
      }

      const tempId = Math.random().toString(36).substring(7);
      const newVideo: UploadedVideo = {
        media_id: tempId,
        blob_name: '',
        media_type: file.type,
        file_size: file.size,
        original_filename: file.name,
        status: 'uploading',
        progress: 0
      };

      setUploadedVideos(prev => [newVideo, ...prev]);

      try {
        // Use chunked upload for large files (>100MB)
        if (shouldUseChunkedUpload(file)) {
          const uploader = new ChunkedUploader(file, {
            preset: selectedPreset,
            maxFrames: maxFrames,
            useSceneDetection: sceneDetectionEnabled,
            useHierarchicalSummary: hierarchicalSummaryEnabled,
            blockSizeMb: 8,
            concurrency: 4,
            onProgress: (progress: UploadProgress) => {
              setUploadedVideos(prev => prev.map(v =>
                v.media_id === tempId ? {
                  ...v,
                  progress: progress.percent,
                  upload_speed: progress.speedBytesPerSecond 
                    ? `${formatBytes(progress.speedBytesPerSecond)}/s` 
                    : undefined,
                  eta: progress.estimatedSecondsRemaining 
                    ? formatEta(progress.estimatedSecondsRemaining)
                    : undefined,
                } : v
              ));
            },
          });

          const result = await uploader.upload();

          if (result.success && result.mediaId) {
            setUploadedVideos(prev => prev.map(v =>
              v.media_id === tempId ? {
                ...v,
                media_id: result.mediaId!,
                blob_name: result.blobName || '',
                job_id: result.jobId,
                status: 'processing',
                progress: 0,
                upload_speed: undefined,
                eta: undefined,
              } : v
            ));

            pollProcessingStatus(result.mediaId, result.jobId);
          } else {
            throw new Error(result.error || 'Chunked upload failed');
          }
        } else {
          // Use standard upload for smaller files
          let response;
          if (useOptimizedPipeline) {
            response = await apiClient.uploadVideoOptimized(file, {
              preset: selectedPreset,
              maxFrames: maxFrames,
              useSceneDetection: sceneDetectionEnabled,
              useHierarchicalSummary: hierarchicalSummaryEnabled,
            });
          } else {
            response = await apiClient.uploadVideo(file, selectedPreset, maxFrames);
          }
          const { media_id, blob_name, job_id } = response;

          setUploadedVideos(prev => prev.map(v =>
            v.media_id === tempId ? {
              ...v,
              media_id,
              blob_name,
              job_id,
              status: 'processing',
              progress: 0
            } : v
          ));

          pollProcessingStatus(media_id, job_id);
        }
      } catch (error) {
        console.error('Upload error:', error);
        setUploadedVideos(prev => prev.map(v =>
          v.media_id === tempId ? {
            ...v,
            status: 'error',
            error_message: error instanceof Error ? error.message : 'Upload failed'
          } : v
        ));
      }
    }
  }, [hierarchicalSummaryEnabled, maxFrames, pollProcessingStatus, sceneDetectionEnabled, selectedPreset, useOptimizedPipeline]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      handleFiles(files);
    }
  }, [handleFiles]);

  return (
    <div className="w-full">
      {/* Drop Zone */}
      <div
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`
          relative group cursor-pointer
          bg-white rounded-2xl p-12
          border-2 border-dashed
          transition-all duration-300 ease-out
          flex flex-col items-center justify-center text-center
          shadow-xl shadow-gray-200/50
          ${isDragging
            ? 'border-indigo-500 bg-indigo-50 scale-[1.02] shadow-indigo-200/50'
            : 'border-gray-200 hover:border-indigo-300 hover:bg-gray-50'
          }
        `}
      >
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileInput}
          className="hidden"
          accept="video/*"
          multiple
        />

        <div className={`
          w-20 h-20 rounded-2xl flex items-center justify-center mb-6 transition-all duration-300
          ${isDragging
            ? 'bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/30 scale-110'
            : 'bg-gradient-to-br from-gray-100 to-gray-200 text-gray-400 group-hover:from-indigo-100 group-hover:to-purple-100 group-hover:text-indigo-500'
          }
        `}>
          <CloudUpload className="w-10 h-10" />
        </div>

        <h3 className="text-xl font-bold text-gray-900 mb-2">
          Drop videos here
        </h3>
        <p className="text-gray-500">
          or <span className="text-indigo-600 font-medium">click to browse</span> files
        </p>

        <div className="flex items-center gap-2 mt-6 text-xs text-gray-400">
          <Film className="w-4 h-4" />
          <span>MP4, MOV, AVI, WebM supported</span>
          <span>• Up to {UPLOAD.MAX_FILES} videos</span>
        </div>
      </div>

      {uploadError && (
        <div role="alert" className="mt-4 rounded-xl border border-red-100 bg-red-50 p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-600">{uploadError}</p>
        </div>
      )}

      {/* Upload List */}
      {uploadedVideos.length > 0 && (
        <div className="mt-8 space-y-3">
          <h4 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">
            Upload Queue
          </h4>

          {uploadedVideos.map((video) => (
            <UploadStatusCard
              key={video.media_id}
              video={video}
              onViewAnalysis={onVideoProcessed}
            />
          ))}
        </div>
      )}
    </div>
  );
}
