'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/layout';
import { VideoGrid } from '@/components/library';
import RequireAuth from '@/components/RequireAuth';

interface Video {
  id: string;
  original_filename: string;
  media_type?: string;
  file_size?: number;
  uploaded_at?: string;
  processed?: boolean;
  processing_status?: string;
  duration?: number;
  frames_analyzed?: number;
  thumbnail_url?: string;
}

export default function LibraryPage() {
  const router = useRouter();
  const [currentMode, setCurrentMode] = useState<'single' | 'library'>('library');
  const [selectedVideoId] = useState<string | undefined>();

  const handleSelectVideo = (video: Video) => {
    // Navigate to chat with this video
    router.push(`/chat/new?videoId=${video.id}`);
  };

  return (
    <RequireAuth>
      <div className="flex h-screen bg-gradient-to-br from-[var(--background)] via-[var(--surface)] to-amber-1 overflow-hidden">
        {/* Decorative Elements */}
        <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
          <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-amber-3/40 to-amber-4/40 rounded-full blur-3xl"></div>
          <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-[var(--sage-3)]/30 to-[var(--sage-4)]/30 rounded-full blur-3xl"></div>
        </div>

        {/* Sidebar */}
        <div className="relative z-10 flex-shrink-0 w-0 md:w-auto overflow-visible">
          <Sidebar
            currentMode={currentMode}
            onModeChange={setCurrentMode}
            onNewChat={() => router.push('/chat/new')}
          />
        </div>

        {/* Main Content */}
        <main className="relative z-10 flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="px-4 md:px-6 py-4 md:py-5 border-b border-[var(--sage-3)] bg-[var(--surface)]/50 backdrop-blur-sm pl-16 md:pl-6">
            <h1 className="text-xl md:text-2xl font-bold text-[var(--foreground)]">Video Library</h1>
            <p className="text-[var(--sage-9)] mt-1">
              Browse and manage your processed videos
            </p>
          </div>

          {/* Video Grid */}
          <div className="flex-1 overflow-hidden">
            <VideoGrid
              onSelectVideo={handleSelectVideo}
              selectedVideoId={selectedVideoId}
            />
          </div>
        </main>
      </div>
    </RequireAuth>
  );
}
