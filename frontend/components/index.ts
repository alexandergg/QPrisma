/**
 * Components barrel export
 * Re-exports all components for cleaner imports
 */

// Editor components
export * from './editor';

// Chat components
export * from './chat';

// Layout components
export * from './layout';

// Library components
export * from './library';

// Upload components
export * from './upload';

// Standalone components
export { default as ChapterNavigation } from './ChapterNavigation';
export { default as PipelineVisualizer } from './PipelineVisualizer';
export { default as ProcessingConfig } from './ProcessingConfig';
export { default as RequireAuth } from './RequireAuth';
export { default as VideoOverlay } from './VideoOverlay';
export { default as VideoProcessingStudio } from './VideoProcessingStudio';
export { default as VideoUpload } from './VideoUpload';

// Error handling and loading
export { ErrorBoundary, withErrorBoundary } from './ErrorBoundary';
export {
  Skeleton,
  SkeletonText,
  SkeletonAvatar,
  SkeletonVideoCard,
  SkeletonClipCard,
  SkeletonChatMessage,
  SkeletonTableRow,
  SkeletonSidebarItem,
  SkeletonPage,
} from './Skeleton';
