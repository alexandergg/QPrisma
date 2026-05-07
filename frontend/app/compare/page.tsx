'use client';

import React, { useState, useCallback, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/layout';
import { VideoGrid } from '@/components/library';
import CompareView from '@/components/compare/CompareView';
import RequireAuth from '@/components/RequireAuth';
import { GitCompare, ArrowLeft, CheckCircle2 } from 'lucide-react';
import type { ChatMode } from '@/components/layout/Sidebar';
import { videoChatHref } from '@/lib/routes';

interface CompareVideo {
  id: string;
  name: string;
  thumbnail?: string;
  duration?: number;
  entities?: string[];
  topics?: string[];
  uploadedAt?: string;
}

export default function ComparePage() {
  const router = useRouter();
  const [sidebarMode, setSidebarMode] = useState<ChatMode>('single');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);

  // Build CompareVideo objects from selected IDs
  // In a real integration the full video data would come from an API or context;
  // here we use the IDs as placeholder names until the grid callback provides full data.

  const handleSelectionChange= useCallback((ids: string[]) => {
    setSelectedIds(ids.slice(0, 3));
  }, []);

  const handleRemoveVideo = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = prev.filter((v) => v !== id);
      if (next.length < 2) {
        setComparing(false);
      }
      return next;
    });
  }, []);

  const compareVideos = useMemo<CompareVideo[]>(
    () =>
      selectedIds.map(
        (id) => ({
            id,
            name: `Video ${id.slice(0, 8)}`,
          })
      ),
    [selectedIds]
  );

  const handleNewChat = useCallback(() => router.push('/'), [router]);

  return (
    <RequireAuth>
      <div className="flex min-h-screen bg-[var(--background)]">
        <Sidebar
          currentMode={sidebarMode}
          onModeChange={setSidebarMode}
          onNewChat={handleNewChat}
        />

        <main className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <header className="sticky top-0 z-10 bg-[var(--surface)]/80 backdrop-blur-xl border-b border-[var(--border)] px-6 py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-[var(--radius-lg)] bg-[var(--violet-2)] flex items-center justify-center">
                  <GitCompare className="w-5 h-5 text-[var(--violet-8)]" />
                </div>
                <div>
                  <h1 className="text-xl font-bold text-[var(--foreground)]">
                    Compare Videos
                  </h1>
                  <p className="text-xs text-[var(--text-secondary)]">
                    Select 2–3 videos to compare insights side by side
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                {selectedIds.length > 0 && (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-[var(--radius-full)] bg-[var(--violet-2)] text-[var(--violet-8)] border border-[var(--violet-4)]">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    {selectedIds.length} selected
                  </span>
                )}

                {comparing ? (
                  <button
                    onClick={() => setComparing(false)}
                    className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-[var(--radius-lg)] bg-[var(--surface-elevated)] text-[var(--foreground)] border border-[var(--border)] hover:bg-[var(--sage-2)] transition-colors"
                  >
                    <ArrowLeft className="w-4 h-4" />
                    Back to selection
                  </button>
                ) : (
                  <button
                    onClick={() => setComparing(true)}
                    disabled={selectedIds.length < 2}
                    className="inline-flex items-center gap-2 px-5 py-2 text-sm font-semibold rounded-[var(--radius-lg)] bg-[var(--violet-8)] text-white hover:bg-[var(--violet-9)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-[var(--shadow-sm)]"
                  >
                    <GitCompare className="w-4 h-4" />
                    Compare
                  </button>
                )}
              </div>
            </div>
          </header>

          {/* Content */}
          <div className="flex-1 overflow-y-auto">
            {comparing ? (
              <div className="p-6">
                <CompareView
                  videos={compareVideos}
                  onRemoveVideo={handleRemoveVideo}
                  onSelectVideo={(id) => router.push(videoChatHref(id))}
                />
              </div>
            ) : (
              <VideoGrid
                selectionMode="multiple"
                selectedVideoIds={selectedIds}
                onSelectionChange={handleSelectionChange}
              />
            )}
          </div>
        </main>
      </div>
    </RequireAuth>
  );
}
