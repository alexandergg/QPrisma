'use client';

import React from 'react';
import {
  CloudUpload,
  AudioLines,
  Mic,
  Eye,
  Layers,
  Network,
  Brain,
  CheckCircle,
  AlertCircle,
  Loader2,
} from 'lucide-react';

export type ProcessingStepStatus = 'pending' | 'in_progress' | 'completed' | 'error';

export interface ProcessingStepData {
  id: string;
  name: string;
  status: ProcessingStepStatus;
  progress?: number;
  details?: string;
  startTime?: Date;
  endTime?: Date;
}

interface ProcessingStepProps {
  step: ProcessingStepData;
  isLast?: boolean;
}

const STEP_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  upload: CloudUpload,
  audio: AudioLines,
  transcribe: Mic,
  frames: Eye,
  scenes: Layers,
  graph: Network,
  embeddings: Brain,
};

export default function ProcessingStep({ step, isLast = false }: ProcessingStepProps) {
  const Icon = STEP_ICONS[step.id] || Loader2;

  const statusStyles = {
    pending: {
      icon: 'bg-gray-100 text-gray-400',
      text: 'text-gray-400',
      line: 'bg-gray-200',
    },
    in_progress: {
      icon: 'bg-indigo-100 text-indigo-600',
      text: 'text-indigo-600',
      line: 'bg-indigo-200',
    },
    completed: {
      icon: 'bg-green-100 text-green-600',
      text: 'text-gray-600',
      line: 'bg-green-400',
    },
    error: {
      icon: 'bg-red-100 text-red-600',
      text: 'text-red-600',
      line: 'bg-red-200',
    },
  };

  const styles = statusStyles[step.status];

  return (
    <div className="flex items-start gap-4">
      {/* Icon & Line */}
      <div className="flex flex-col items-center">
        <div
          className={`w-10 h-10 rounded-xl flex items-center justify-center ${styles.icon} transition-colors`}
        >
          {step.status === 'completed' ? (
            <CheckCircle className="w-5 h-5" />
          ) : step.status === 'error' ? (
            <AlertCircle className="w-5 h-5" />
          ) : step.status === 'in_progress' ? (
            <Icon className="w-5 h-5 animate-pulse" />
          ) : (
            <Icon className="w-5 h-5" />
          )}
        </div>
        {!isLast && (
          <div className={`w-0.5 h-8 mt-2 ${styles.line} transition-colors`} />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pt-2">
        <div className="flex items-center justify-between">
          <p className={`font-medium ${styles.text} transition-colors`}>
            {step.name}
          </p>
          {step.status === 'in_progress' && step.progress !== undefined && (
            <span className="text-sm text-indigo-600 font-mono">
              {step.progress}%
            </span>
          )}
          {step.status === 'completed' && step.endTime && step.startTime && (
            <span className="text-xs text-gray-400">
              {((step.endTime.getTime() - step.startTime.getTime()) / 1000).toFixed(1)}s
            </span>
          )}
        </div>

        {/* Details */}
        {step.details && (
          <p className="text-sm text-gray-500 mt-0.5 truncate">{step.details}</p>
        )}

        {/* Progress bar for in_progress */}
        {step.status === 'in_progress' && step.progress !== undefined && (
          <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-all duration-300"
              style={{ width: `${step.progress}%` }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
