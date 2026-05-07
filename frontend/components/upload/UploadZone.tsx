'use client';

import React, { useState, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import { CloudUpload, Film, X } from 'lucide-react';
import { UPLOAD } from '@/lib/constants';

interface UploadZoneProps {
  onFilesSelected: (files: File[]) => void;
  isUploading?: boolean;
  acceptedFormats?: string[];
  maxSize?: number; // in bytes
  multiple?: boolean;
  maxFiles?: number;
}

const DEFAULT_FORMATS = ['video/mp4', 'video/mov', 'video/avi', 'video/webm', 'video/quicktime'];
const DEFAULT_MAX_SIZE = UPLOAD.MAX_FILE_SIZE;

export default function UploadZone({
  onFilesSelected,
  isUploading = false,
  acceptedFormats = DEFAULT_FORMATS,
  maxSize = DEFAULT_MAX_SIZE,
  multiple = true,
  maxFiles = UPLOAD.MAX_FILES,
}: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const formatSize = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  const validateFiles = useCallback((files: File[]): File[] => {
    const validFiles: File[] = [];
    const errors: string[] = [];
    const maxSelectable = multiple ? maxFiles : 1;
    const filesToValidate = files.slice(0, maxSelectable);

    if (files.length > maxSelectable) {
      errors.push(
        `You can upload up to ${maxSelectable} video${maxSelectable === 1 ? '' : 's'} at once. ${filesToValidate.length} of ${files.length} selected files will be added.`
      );
    }

    for (const file of filesToValidate) {
      // Check file type
      if (!acceptedFormats.some((format) => file.type.startsWith(format.split('/')[0]))) {
        errors.push(`${file.name}: Invalid file type`);
        continue;
      }

      // Check file size
      if (file.size > maxSize) {
        errors.push(`${file.name}: File too large (max ${formatSize(maxSize)})`);
        continue;
      }

      validFiles.push(file);
    }

    if (errors.length > 0) {
      setError(errors.join('. '));
    } else {
      setError(null);
    }

    return validFiles;
  }, [acceptedFormats, maxFiles, maxSize, multiple]);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isUploading) {
      setIsDragging(true);
    }
  }, [isUploading]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      if (isUploading) return;

      const files = Array.from(e.dataTransfer.files);
      const validFiles = validateFiles(files);

      if (validFiles.length > 0) {
        onFilesSelected(multiple ? validFiles : [validFiles[0]]);
      }
    },
    [isUploading, multiple, onFilesSelected, validateFiles]
  );

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const files = Array.from(e.target.files);
      const validFiles = validateFiles(files);

      if (validFiles.length > 0) {
        onFilesSelected(multiple ? validFiles : [validFiles[0]]);
      }
    }

    // Reset input
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleClick = () => {
    if (!isUploading) {
      fileInputRef.current?.click();
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleClick();
    }
  };

  return (
    <div className="w-full">
      <motion.div
        animate={isDragging
          ? { scale: 1.02, borderColor: 'var(--violet-6)' }
          : { scale: 1, borderColor: 'var(--border)' }
        }
        transition={{ type: 'spring', damping: 20, stiffness: 300 }}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        role="button"
        tabIndex={isUploading ? -1 : 0}
        aria-disabled={isUploading}
        aria-label="Upload video files"
        className={`
          relative group cursor-pointer
          bg-white rounded-2xl p-12
          border-2 border-dashed
          transition-colors duration-300 ease-out
          flex flex-col items-center justify-center text-center
          shadow-xl shadow-gray-200/50
          ${isUploading ? 'opacity-50 cursor-not-allowed' : ''}
          ${
            isDragging
              ? 'border-violet-500 bg-violet-50 shadow-violet-200/50'
              : 'border-gray-200 hover:border-violet-300 hover:bg-gray-50'
          }
        `}
      >
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileInput}
          className="hidden"
          accept="video/*"
          multiple={multiple}
          disabled={isUploading}
          aria-label="Choose video files to upload"
        />

        <div
          className={`
            w-20 h-20 rounded-2xl flex items-center justify-center mb-6 transition-all duration-300
            ${
              isDragging
                ? 'bg-gradient-to-br from-violet-500 to-violet-600 text-white shadow-lg shadow-violet-500/30 scale-110'
                : 'bg-gradient-to-br from-gray-100 to-gray-200 text-gray-400 group-hover:from-violet-100 group-hover:to-violet-100 group-hover:text-violet-600'
            }
          `}
        >
          <CloudUpload className="w-10 h-10" />
        </div>

        <h3 className="text-xl font-bold text-gray-900 mb-2">
          {isDragging ? 'Drop your videos here' : 'Drop videos here'}
        </h3>
        <p className="text-gray-500">
          or <span className="text-violet-600 font-medium">click to browse</span> files
        </p>

        <div className="flex items-center gap-2 mt-6 text-xs text-gray-400">
          <Film className="w-4 h-4" />
          <span>
            MP4, MOV, AVI, WebM • Max {formatSize(maxSize)} each
            {multiple ? ` • Up to ${maxFiles} videos` : ''}
          </span>
        </div>
      </motion.div>

      {/* Error Message */}
      {error && (
        <div role="alert" className="mt-4 bg-red-50 border border-red-100 rounded-xl p-4 flex items-start gap-3">
          <X className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-red-600 font-medium">Upload Error</p>
            <p className="text-sm text-red-500 mt-1">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}
