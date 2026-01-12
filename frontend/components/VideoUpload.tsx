'use client';

import React, { useState, useCallback, useRef } from 'react';
import { Upload, Film, AlertCircle, CheckCircle, Loader, X, Play, Eye, Database, FileVideo, CloudUpload, Sparkles } from 'lucide-react';
import { apiClient } from '@/lib/api';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface UploadedVideo {
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
}

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
  const [uploadedVideos, setUploadedVideos] = useState<UploadedVideo[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      handleFiles(files);
    }
  }, [selectedPreset, maxFrames, useOptimizedPipeline, sceneDetectionEnabled, hierarchicalSummaryEnabled]);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(Array.from(e.target.files));
    }
  };

  const handleFiles = async (files: File[]) => {
    setIsUploading(true);

    for (const file of files) {
      if (!file.type.startsWith('video/')) {
        alert(`File ${file.name} is not a video`);
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
        // Upload video with authentication - use optimized pipeline if enabled
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

      } catch (error) {
        console.error('Upload error:', error);
        setUploadedVideos(prev => prev.map(v =>
          v.media_id === tempId ? {
            ...v,
            status: 'error',
            error_message: 'Upload failed'
          } : v
        ));
      }
    }
    setIsUploading(false);
  };

  const pollProcessingStatus = async (mediaId: string, jobId?: string) => {
    if (!jobId) {
      setUploadedVideos(prev => prev.map(v =>
        v.media_id === mediaId ? {
          ...v,
          status: 'error',
          error_message: 'Missing job_id from upload response'
        } : v
      ));
      return;
    }

    let attempts = 0;
    const maxAttempts = 300;

    const pollInterval = setInterval(async () => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(pollInterval);
        setUploadedVideos(prev => prev.map(v =>
          v.media_id === mediaId ? {
            ...v,
            status: 'error',
            error_message: 'Processing timeout'
          } : v
        ));
        return;
      }

      try {
        const token = localStorage.getItem('auth_token');
        const response = await fetch(`${API_URL}/jobs/${jobId}`, {
          headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        });

        if (!response.ok) {
          console.error('Job polling failed with status:', response.status);
          return;
        }

        const data = await response.json();
        const status = data?.status as string | undefined;

        setUploadedVideos(prev => prev.map(v =>
          v.media_id === mediaId ? {
            ...v,
            progress: typeof data?.progress === 'number' ? data.progress : v.progress,
          } : v
        ));

        if (status === 'success') {
          clearInterval(pollInterval);
          setUploadedVideos(prev => prev.map(v =>
            v.media_id === mediaId ? {
              ...v,
              status: 'completed',
              progress: 100
            } : v
          ));
          onVideoProcessed?.(mediaId);
        } else if (status === 'failure' || status === 'cancelled') {
          clearInterval(pollInterval);
          setUploadedVideos(prev => prev.map(v =>
            v.media_id === mediaId ? {
              ...v,
              status: 'error',
              error_message: data?.error || 'Processing failed'
            } : v
          ));
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    }, 3000);
  };

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
        </div>
      </div>

      {/* Upload List */}
      {uploadedVideos.length > 0 && (
        <div className="mt-8 space-y-3">
          <h4 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">
            Upload Queue
          </h4>

          {uploadedVideos.map((video) => (
            <div
              key={video.media_id}
              className="bg-white rounded-xl p-5 border border-gray-100 shadow-lg shadow-gray-200/50 flex items-center gap-5 group hover:shadow-xl hover:shadow-indigo-200/20 transition-all"
            >
              {/* Icon Status */}
              <div className="flex-shrink-0">
                {video.status === 'uploading' && (
                  <div className="w-12 h-12 rounded-xl bg-gray-100 flex items-center justify-center">
                    <Loader className="w-5 h-5 text-indigo-500 animate-spin" />
                  </div>
                )}
                {video.status === 'processing' && (
                  <div className="w-12 h-12 rounded-xl bg-indigo-100 flex items-center justify-center">
                    <Sparkles className="w-5 h-5 text-indigo-600 animate-pulse" />
                  </div>
                )}
                {video.status === 'completed' && (
                  <div className="w-12 h-12 rounded-xl bg-green-100 flex items-center justify-center">
                    <CheckCircle className="w-6 h-6 text-green-600" />
                  </div>
                )}
                {video.status === 'error' && (
                  <div className="w-12 h-12 rounded-xl bg-red-100 flex items-center justify-center">
                    <AlertCircle className="w-6 h-6 text-red-600" />
                  </div>
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-start mb-2">
                  <h5 className="font-semibold text-gray-900 truncate">
                    {video.original_filename}
                  </h5>
                  {video.status === 'completed' && (
                    <button
                      onClick={() => onVideoProcessed?.(video.media_id)}
                      className="px-4 py-2 bg-gradient-to-r from-indigo-500 to-purple-600 text-white rounded-lg text-sm font-semibold hover:from-indigo-600 hover:to-purple-700 transition-all flex items-center gap-2 shadow-lg shadow-indigo-500/30"
                    >
                      View Analysis
                      <Play className="w-3 h-3 fill-white" />
                    </button>
                  )}
                </div>

                {/* Progress Bar */}
                {video.status === 'uploading' && (
                  <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-all duration-300"
                      style={{ width: `${video.progress}%` }}
                    />
                  </div>
                )}

                {/* Status Text */}
                <div className="flex items-center gap-4 mt-2 text-sm font-medium">
                  {video.status === 'uploading' && (
                    <span className="text-indigo-600">Uploading {video.progress}%...</span>
                  )}
                  {video.status === 'processing' && (
                    <span className="text-indigo-600 flex items-center gap-2">
                      <span className="w-2 h-2 bg-indigo-500 rounded-full animate-pulse"></span>
                      Processing with AI...
                    </span>
                  )}
                  {video.status === 'completed' && (
                    <span className="text-green-600 flex items-center gap-2">
                      <CheckCircle className="w-4 h-4" />
                      Analysis Complete
                      {video.frames_analyzed && (
                        <>
                          <span className="text-gray-300">|</span>
                          <span className="text-gray-500">{video.frames_analyzed} frames processed</span>
                        </>
                      )}
                    </span>
                  )}
                  {video.status === 'error' && (
                    <span className="text-red-600 flex items-center gap-2">
                      <AlertCircle className="w-4 h-4" />
                      {video.error_message}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
