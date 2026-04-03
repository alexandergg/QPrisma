'use client';

import React, { useState, useCallback, useRef } from 'react';
import { CloudUpload, Film, X } from 'lucide-react';

interface UploadZoneProps {
  onFilesSelected: (files: File[]) => void;
  isUploading?: boolean;
  acceptedFormats?: string[];
  maxSize?: number; // in bytes
  multiple?: boolean;
}

const DEFAULT_FORMATS = ['video/mp4', 'video/mov', 'video/avi', 'video/webm', 'video/quicktime'];
const DEFAULT_MAX_SIZE = 10 * 1024 * 1024 * 1024; // 10GB

export default function UploadZone({
  onFilesSelected,
  isUploading = false,
  acceptedFormats = DEFAULT_FORMATS,
  maxSize = DEFAULT_MAX_SIZE,
  multiple = true,
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

    for (const file of files) {
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
  }, [acceptedFormats, maxSize]);

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

  return (
    <div className="w-full">
      <div
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        className={`
          relative group cursor-pointer
          bg-[var(--surface)] rounded-2xl p-12
          border-2 border-dashed
          transition-all duration-300 ease-out
          flex flex-col items-center justify-center text-center
          shadow-[var(--shadow-xl)]
          ${isUploading ? 'opacity-50 cursor-not-allowed' : ''}
          ${
            isDragging
              ? 'border-[var(--amber-6)] bg-[var(--amber-1)] scale-[1.02]'
              : 'border-[var(--border)] hover:border-[var(--amber-6)] hover:bg-[var(--surface-elevated)]'
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
        />

        <div
          className={`
            w-20 h-20 rounded-2xl flex items-center justify-center mb-6 transition-all duration-300
            ${
              isDragging
                ? 'bg-gradient-to-br from-[var(--amber-7)] to-[var(--amber-9)] text-white shadow-lg scale-110'
                : 'bg-[var(--surface-elevated)] text-[var(--text-tertiary)] group-hover:bg-[var(--amber-2)] group-hover:text-[var(--amber-8)]'
            }
          `}
        >
          <CloudUpload className="w-10 h-10" />
        </div>

        <h3 className="text-xl font-bold text-[var(--foreground)] mb-2">
          {isDragging ? 'Drop your videos here' : 'Drop videos here'}
        </h3>
        <p className="text-[var(--text-secondary)]">
          or <span className="text-[var(--amber-8)] font-medium">click to browse</span> files
        </p>

        <div className="flex items-center gap-2 mt-6 text-xs text-[var(--text-tertiary)]">
          <Film className="w-4 h-4" />
          <span>MP4, MOV, AVI, WebM • Max {formatSize(maxSize)}</span>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="mt-4 bg-[var(--rose-3)]/30 border border-[var(--rose-7)]/20 rounded-xl p-4 flex items-start gap-3">
          <X className="w-5 h-5 text-[var(--rose-8)] flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-[var(--rose-8)] font-medium">Upload Error</p>
            <p className="text-sm text-[var(--rose-8)] mt-1">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}
