'use client';

import React from 'react';

interface SkeletonProps {
  className?: string;
  animate?: boolean;
}

/**
 * Base skeleton component with animation
 */
export function Skeleton({ className = '', animate = true }: SkeletonProps) {
  return (
    <div
      className={`bg-gray-200 rounded ${animate ? 'animate-pulse' : ''} ${className}`}
    />
  );
}

/**
 * Text line skeleton
 */
export function SkeletonText({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-4 ${i === lines - 1 ? 'w-3/4' : 'w-full'}`}
        />
      ))}
    </div>
  );
}

/**
 * Avatar/circle skeleton
 */
export function SkeletonAvatar({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sizeClasses = {
    sm: 'w-8 h-8',
    md: 'w-12 h-12',
    lg: 'w-16 h-16',
  };
  return <Skeleton className={`${sizeClasses[size]} rounded-full`} />;
}

/**
 * Video card skeleton
 */
export function SkeletonVideoCard() {
  return (
    <div className="bg-white rounded-2xl overflow-hidden border border-gray-100 shadow-sm">
      {/* Thumbnail */}
      <Skeleton className="aspect-video w-full" />
      
      {/* Content */}
      <div className="p-4 space-y-3">
        <Skeleton className="h-5 w-3/4" />
        <div className="flex gap-2">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-20" />
        </div>
        <Skeleton className="h-6 w-20 rounded-full" />
      </div>
    </div>
  );
}

/**
 * Clip card skeleton
 */
export function SkeletonClipCard() {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
      <div className="flex items-center gap-3">
        <Skeleton className="w-6 h-6 rounded" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </div>
      <div className="flex gap-2">
        <Skeleton className="h-6 w-16 rounded-full" />
        <Skeleton className="h-6 w-12 rounded-full" />
      </div>
    </div>
  );
}

/**
 * Chat message skeleton
 */
export function SkeletonChatMessage({ isUser = false }: { isUser?: boolean }) {
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <SkeletonAvatar size="sm" />
      <div className={`flex-1 max-w-[80%] space-y-2 ${isUser ? 'items-end' : ''}`}>
        <Skeleton className={`h-4 ${isUser ? 'w-1/2 ml-auto' : 'w-3/4'}`} />
        <Skeleton className={`h-4 ${isUser ? 'w-1/3 ml-auto' : 'w-2/3'}`} />
        {!isUser && <Skeleton className="h-4 w-1/2" />}
      </div>
    </div>
  );
}

/**
 * Table row skeleton
 */
export function SkeletonTableRow({ columns = 4 }: { columns?: number }) {
  return (
    <div className="flex items-center gap-4 py-3 border-b border-gray-100">
      {Array.from({ length: columns }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-4 ${i === 0 ? 'w-1/4' : 'flex-1'}`}
        />
      ))}
    </div>
  );
}

/**
 * Sidebar item skeleton
 */
export function SkeletonSidebarItem() {
  return (
    <div className="flex items-center gap-3 px-3 py-2">
      <Skeleton className="w-5 h-5 rounded" />
      <Skeleton className="h-4 flex-1" />
    </div>
  );
}

/**
 * Full page loading skeleton
 */
export function SkeletonPage() {
  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-4 w-64" />
        </div>
        <Skeleton className="h-10 w-32 rounded-lg" />
      </div>

      {/* Content grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonVideoCard key={i} />
        ))}
      </div>
    </div>
  );
}

export default Skeleton;
