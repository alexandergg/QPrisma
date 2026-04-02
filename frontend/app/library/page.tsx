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
      <div className="flex h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 overflow-hidden">
        {/* Decorative Elements */}
        <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
          <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl"></div>
          <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl"></div>
        </div>

        {/* Sidebar */}
        <div className="relative z-10 flex-shrink-0">
          <Sidebar
            currentMode={currentMode}
            onModeChange={setCurrentMode}
            onNewChat={() => router.push('/chat/new')}
          />
        </div>

        {/* Main Content */}
        <main className="relative z-10 flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="px-6 py-5 border-b border-gray-100 bg-white/50 backdrop-blur-sm">
            <h1 className="text-2xl font-bold text-gray-900">Video Library</h1>
            <p className="text-gray-500 mt-1">
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
