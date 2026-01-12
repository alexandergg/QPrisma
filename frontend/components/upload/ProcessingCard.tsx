'use client';

import React, { useState, useEffect } from 'react';
import { Film, X, CheckCircle, AlertCircle, Sparkles, Play } from 'lucide-react';
import ProcessingStep, { ProcessingStepData, ProcessingStepStatus } from './ProcessingStep';

interface ProcessingCardProps {
  fileName: string;
  fileSize: number;
  jobId?: string;
  initialSteps?: ProcessingStepData[];
  onComplete?: (mediaId: string) => void;
  onError?: (error: string) => void;
  onViewVideo?: (mediaId: string) => void;
  onCancel?: () => void;
  mediaId?: string;
}

const DEFAULT_STEPS: ProcessingStepData[] = [
  { id: 'upload', name: 'Uploading to cloud', status: 'pending' },
  { id: 'audio', name: 'Extracting audio', status: 'pending' },
  { id: 'transcribe', name: 'Transcribing speech', status: 'pending' },
  { id: 'frames', name: 'Analyzing visual frames', status: 'pending' },
  { id: 'scenes', name: 'Detecting scenes', status: 'pending' },
  { id: 'graph', name: 'Building knowledge graph', status: 'pending' },
  { id: 'embeddings', name: 'Generating embeddings', status: 'pending' },
];

// Map backend stage names to frontend step IDs
const STAGE_TO_STEP: Record<string, string> = {
  // Download/upload stages
  downloading: 'upload',
  started: 'upload',
  
  // Frame extraction and analysis stages
  extracting: 'frames',
  analyzing: 'frames',
  batch_submit: 'frames',
  batch_wait: 'frames',
  batch_results: 'frames',
  
  // Transcription stages
  transcribing: 'transcribe',
  audio: 'audio',
  
  // Scene detection
  scenes: 'scenes',
  
  // Knowledge graph
  graph: 'graph',
  
  // Embeddings
  embeddings: 'embeddings',
  
  // Direct step IDs for compatibility
  upload: 'upload',
  transcribe: 'transcribe',
  frames: 'frames',
};

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export default function ProcessingCard({
  fileName,
  fileSize,
  jobId,
  initialSteps,
  onComplete,
  onError,
  onViewVideo,
  onCancel,
  mediaId,
}: ProcessingCardProps) {
  const [steps, setSteps] = useState<ProcessingStepData[]>(initialSteps || DEFAULT_STEPS);
  const [overallProgress, setOverallProgress] = useState(0);
  const [status, setStatus] = useState<'processing' | 'completed' | 'error'>('processing');
  const [error, setError] = useState<string | null>(null);
  const [estimatedTime, setEstimatedTime] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [debugInfo, setDebugInfo] = useState<string>('');

  // Mark upload step as completed when we get a jobId (upload to blob is done)
  useEffect(() => {
    if (jobId) {
      console.log('[ProcessingCard] jobId received:', jobId);
      setDebugInfo(`Job ID: ${jobId.substring(0, 8)}...`);
      setSteps((prevSteps) =>
        prevSteps.map((step) =>
          step.id === 'upload'
            ? { ...step, status: 'completed' as ProcessingStepStatus, progress: 100, endTime: new Date() }
            : step
        )
      );
      setOverallProgress(10); // Upload is ~10% of total progress
    }
  }, [jobId]);

  // Fallback polling for job status (if WebSocket doesn't work)
  useEffect(() => {
    if (!jobId || status === 'completed' || status === 'error') return;
    
    const pollInterval = setInterval(async () => {
      if (wsConnected) return; // Skip polling if WebSocket is working
      
      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
        const token = localStorage.getItem('auth_token');
        const response = await fetch(`${apiUrl}/media/${mediaId}/status`, {
          headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        });
        
        if (response.ok) {
          const data = await response.json();
          console.log('[ProcessingCard] Poll status:', data);
          
          if (data.processing_status === 'completed') {
            setStatus('completed');
            setOverallProgress(100);
            setSteps((prevSteps) =>
              prevSteps.map((step) => ({
                ...step,
                status: 'completed' as ProcessingStepStatus,
                progress: 100,
                endTime: new Date(),
              }))
            );
            onComplete?.(mediaId || '');
            clearInterval(pollInterval);
          } else if (data.processing_status === 'failed') {
            setStatus('error');
            setError(data.error || 'Processing failed');
            clearInterval(pollInterval);
          }
        }
      } catch (e) {
        console.log('[ProcessingCard] Poll error (will retry):', e);
      }
    }, 5000); // Poll every 5 seconds
    
    return () => clearInterval(pollInterval);
  }, [jobId, mediaId, status, wsConnected, onComplete]);

  // WebSocket connection for real-time updates
  useEffect(() => {
    if (!jobId) return;

    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
    console.log('[ProcessingCard] Connecting to WebSocket:', `${wsUrl}/ws/jobs/${jobId}`);
    setDebugInfo(prev => `${prev} | WS: connecting...`);
    const ws = new WebSocket(`${wsUrl}/ws/jobs/${jobId}`);

    ws.onopen = () => {
      console.log('[ProcessingCard] WebSocket connected for job:', jobId);
      setWsConnected(true);
      setDebugInfo(prev => `${prev.replace('connecting...', 'connected')}`);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log('[ProcessingCard] WebSocket message received:', data);

        if (data.type === 'job_progress') {
          const { progress, stage, message, step_progress } = data.payload;
          
          // Map backend stage to frontend step ID
          const stepId = STAGE_TO_STEP[stage] || stage;
          console.log(`[ProcessingCard] Stage mapping: ${stage} -> ${stepId}`);

          // Update overall progress
          setOverallProgress(progress);

          // Update step status
          setSteps((prevSteps) =>
            prevSteps.map((step) => {
              if (step.id === stepId) {
                return {
                  ...step,
                  status: 'in_progress' as ProcessingStepStatus,
                  progress: step_progress || progress,
                  details: message,
                  startTime: step.startTime || new Date(),
                };
              }
              // Mark previous steps as completed
              const stageIndex = prevSteps.findIndex((s) => s.id === stepId);
              const stepIndex = prevSteps.findIndex((s) => s.id === step.id);
              if (stepIndex < stageIndex && step.status !== 'completed') {
                return {
                  ...step,
                  status: 'completed' as ProcessingStepStatus,
                  progress: 100,
                  endTime: new Date(),
                };
              }
              return step;
            })
          );

          // Update estimated time based on progress
          if (progress > 0 && progress < 100) {
            const remaining = Math.ceil((100 - progress) / 10); // Rough estimate
            setEstimatedTime(`~${remaining} min remaining`);
          }
        }

        if (data.type === 'job_completed') {
          setStatus('completed');
          setOverallProgress(100);
          setSteps((prevSteps) =>
            prevSteps.map((step) => ({
              ...step,
              status: 'completed' as ProcessingStepStatus,
              progress: 100,
              endTime: new Date(),
            }))
          );
          onComplete?.(data.payload?.media_id || mediaId || '');
        }

        if (data.type === 'job_failed') {
          setStatus('error');
          setError(data.payload?.error || 'Processing failed');
          onError?.(data.payload?.error || 'Processing failed');
        }
        
        // Handle initial status from server on connect
        if (data.type === 'connected' || data.type === 'heartbeat') {
          console.log('[ProcessingCard] Server heartbeat/connected:', data);
        }
      } catch (e) {
        console.error('[ProcessingCard] WebSocket message parse error:', e);
      }
    };

    ws.onerror = (error) => {
      console.error('[ProcessingCard] WebSocket error:', error);
      setDebugInfo(prev => `${prev} | WS error`);
      setWsConnected(false);
    };

    ws.onclose = (event) => {
      console.log('[ProcessingCard] WebSocket closed for job:', jobId, 'code:', event.code);
      setWsConnected(false);
      setDebugInfo(prev => `${prev} | WS closed (${event.code})`);
    };

    return () => {
      ws.close();
    };
  }, [jobId, mediaId, onComplete, onError]);

  const completedSteps = steps.filter((s) => s.status === 'completed').length;

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-xl shadow-gray-200/50 overflow-hidden">
      {/* Debug Info (temporary) */}
      {debugInfo && (
        <div className="px-4 py-2 bg-gray-100 text-xs text-gray-500 font-mono">
          {debugInfo} | Progress: {overallProgress}%
        </div>
      )}
      {/* Header */}
      <div className="flex items-center gap-4 p-5 border-b border-gray-100">
        <div
          className={`w-12 h-12 rounded-xl flex items-center justify-center ${
            status === 'completed'
              ? 'bg-green-100 text-green-600'
              : status === 'error'
              ? 'bg-red-100 text-red-600'
              : 'bg-indigo-100 text-indigo-600'
          }`}
        >
          {status === 'completed' ? (
            <CheckCircle className="w-6 h-6" />
          ) : status === 'error' ? (
            <AlertCircle className="w-6 h-6" />
          ) : (
            <Film className="w-6 h-6" />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 truncate">{fileName}</h3>
          <p className="text-sm text-gray-500">{formatFileSize(fileSize)}</p>
        </div>

        {status === 'processing' && onCancel && (
          <button
            onClick={onCancel}
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        )}

        {status === 'completed' && onViewVideo && mediaId && (
          <button
            onClick={() => onViewVideo(mediaId)}
            className="px-4 py-2 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl font-medium flex items-center gap-2 shadow-lg shadow-indigo-500/30"
          >
            <Play className="w-4 h-4 fill-white" />
            Start Chatting
          </button>
        )}
      </div>

      {/* Overall Progress */}
      <div className="px-5 py-4 bg-gray-50/50">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">
            {status === 'completed'
              ? 'Processing complete!'
              : status === 'error'
              ? 'Processing failed'
              : `Processing... ${completedSteps}/${steps.length} steps`}
          </span>
          <span className="text-sm font-mono text-indigo-600">{overallProgress}%</span>
        </div>
        <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${
              status === 'completed'
                ? 'bg-green-500'
                : status === 'error'
                ? 'bg-red-500'
                : 'bg-gradient-to-r from-indigo-500 to-purple-500'
            }`}
            style={{ width: `${overallProgress}%` }}
          />
        </div>
        {estimatedTime && status === 'processing' && (
          <p className="text-xs text-gray-400 mt-2 flex items-center gap-1">
            <Sparkles className="w-3 h-3" />
            {estimatedTime}
          </p>
        )}
      </div>

      {/* Steps */}
      <div className="p-5 space-y-0">
        {steps.map((step, index) => (
          <ProcessingStep
            key={step.id}
            step={step}
            isLast={index === steps.length - 1}
          />
        ))}
      </div>

      {/* Error Message */}
      {status === 'error' && error && (
        <div className="px-5 pb-5">
          <div className="bg-red-50 border border-red-100 rounded-xl p-4">
            <p className="text-sm text-red-600">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}
