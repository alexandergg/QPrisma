/**
 * Dynamic imports for code splitting
 * 
 * Use these for heavy components that don't need to be in the initial bundle.
 * Import with: import { DynamicExportModal } from '@/lib/dynamic'
 */

import dynamic from 'next/dynamic';
import { Loader2 } from 'lucide-react';
import React from 'react';

// Loading component for dynamic imports
const LoadingSpinner = () => (
  <div className="flex items-center justify-center p-8">
    <Loader2 className="w-8 h-8 text-indigo-600 animate-spin" />
  </div>
);

const LoadingCard = () => (
  <div className="bg-white rounded-xl border border-gray-200 p-6 animate-pulse">
    <div className="h-4 bg-gray-200 rounded w-3/4 mb-4" />
    <div className="h-4 bg-gray-200 rounded w-1/2" />
  </div>
);

// ============================================================================
// Editor Components (Heavy)
// ============================================================================

/**
 * Export Modal - Only loaded when user clicks export
 */
export const DynamicExportModal = dynamic(
  () => import('@/components/editor/ExportModal'),
  {
    loading: LoadingSpinner,
    ssr: false,
  }
);

/**
 * Timeline Waveform - Heavy component with WaveSurfer.js
 */
export const DynamicTimelineWaveform = dynamic(
  () => import('@/components/editor/TimelineWaveform'),
  {
    loading: () => (
      <div className="h-32 bg-gray-100 rounded-lg animate-pulse" />
    ),
    ssr: false,
  }
);

/**
 * Subtitle Editor - Loaded when editing subtitles
 */
export const DynamicSubtitleEditor = dynamic(
  () => import('@/components/editor/SubtitleEditor'),
  {
    loading: LoadingCard,
    ssr: false,
  }
);

/**
 * Subtitle Overlay - Loaded with video player
 */
export const DynamicSubtitleOverlay = dynamic(
  () => import('@/components/editor/SubtitleOverlay'),
  {
    ssr: false,
  }
);

// ============================================================================
// Chat Components
// ============================================================================

/**
 * Chat Container - Main chat interface
 */
export const DynamicChatContainer = dynamic(
  () => import('@/components/chat/ChatContainer'),
  {
    loading: LoadingSpinner,
    ssr: false,
  }
);

// ============================================================================
// Visualization Components
// ============================================================================

/**
 * Knowledge Graph Viewer - Neo4j NVL based graph visualization
 */
export const DynamicKnowledgeGraphViewer = dynamic(
  () => import('@/components/graph/KnowledgeGraphViewer'),
  {
    loading: () => (
      <div className="h-full bg-gray-50 rounded-lg animate-pulse flex items-center justify-center">
        <span className="text-gray-400">Loading Knowledge Graph...</span>
      </div>
    ),
    ssr: false,
  }
);

/**
 * Pipeline Visualizer - ReactFlow based visualization
 */
export const DynamicPipelineVisualizer = dynamic(
  () => import('@/components/PipelineVisualizer'),
  {
    loading: () => (
      <div className="h-64 bg-gray-50 rounded-lg animate-pulse flex items-center justify-center">
        <span className="text-gray-400">Loading visualization...</span>
      </div>
    ),
    ssr: false,
  }
);

/**
 * Chapter Navigation - Video structure navigation
 */
export const DynamicChapterNavigation = dynamic(
  () => import('@/components/ChapterNavigation'),
  {
    loading: LoadingCard,
    ssr: false,
  }
);

/**
 * Video Overlay - Canvas-based annotations
 */
export const DynamicVideoOverlay = dynamic(
  () => import('@/components/VideoOverlay'),
  {
    ssr: false,
  }
);
