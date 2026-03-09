'use client';

import React from 'react';
import {
  Film,
  AlertCircle,
  CheckCircle,
  Loader,
  Play,
  Sparkles,
} from 'lucide-react';

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
  upload_speed?: string;
  eta?: string;
}

interface UploadStatusCardProps {
  video: UploadedVideo;
  onViewAnalysis?: (mediaId: string) => void;
}

export function UploadStatusCard({ video, onViewAnalysis }: UploadStatusCardProps) {
  return (
    <div className="bg-white rounded-xl p-5 border border-gray-100 shadow-lg shadow-gray-200/50 flex items-center gap-5 group hover:shadow-xl hover:shadow-indigo-200/20 transition-all">
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
              onClick={() => onViewAnalysis?.(video.media_id)}
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
            <span className="text-indigo-600 flex items-center gap-2">
              Uploading {video.progress}%
              {video.upload_speed && (
                <span className="text-gray-400">• {video.upload_speed}</span>
              )}
              {video.eta && (
                <span className="text-gray-400">• ETA: {video.eta}</span>
              )}
            </span>
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
  );
}
