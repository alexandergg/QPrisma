/**
 * Dynamic imports for code splitting
 * 
 * Use these for heavy components that don't need to be in the initial bundle.
 * Import with: import { DynamicChatContainer } from '@/lib/dynamic'
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
