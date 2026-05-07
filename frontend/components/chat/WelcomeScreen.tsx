'use client';

import React, { memo } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  Sparkles,
  Upload,
  Library,
  MessageSquare,
  Network,
  FileText,
  Film,
  ArrowRight,
  Clock,
  GitCompareArrows,
} from 'lucide-react';
import { staggerContainer, staggerItem } from '@/lib/animations';
import { useUserVideos } from '@/hooks/useUserVideos';
import type { MediaItem } from '@/lib/api';

// ---------------------------------------------------------------------------
// Animation variants
// ---------------------------------------------------------------------------

const heroFadeIn = {
  initial: { opacity: 0, y: 16 },
  animate: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.45, ease: [0.4, 0, 0.2, 1] as [number, number, number, number] },
  },
};

const staggerSlow = {
  initial: {},
  animate: { transition: { staggerChildren: 0.08, delayChildren: 0.15 } },
};

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export interface WelcomeScreenProps {
  onUploadVideo?: () => void;
  onBrowseLibrary?: () => void;
  onQuickSuggestion?: (suggestion: string) => void;
  onSelectVideo?: (videoId: string) => void;
  mode?: 'single' | 'library';
  userName?: string;
}

// ---------------------------------------------------------------------------
// Feature cards for new-user view
// ---------------------------------------------------------------------------

const FEATURES = [
  {
    icon: MessageSquare,
    title: 'AI Chat',
    description: 'Ask any question about your video and get instant answers',
    iconColor: 'text-amber-600',
    accentBg: 'from-amber-50 to-orange-50',
  },
  {
    icon: Network,
    title: 'Knowledge Graph',
    description: 'Discover entities, topics and connections automatically',
    iconColor: 'text-violet-600',
    accentBg: 'from-violet-50 to-purple-50',
  },
  {
    icon: FileText,
    title: 'Smart Transcript',
    description: 'Search and navigate every moment with precision',
    iconColor: 'text-sky-600',
    accentBg: 'from-sky-50 to-blue-50',
  },
] as const;

// ---------------------------------------------------------------------------
// Helper — format seconds → "m:ss"
// ---------------------------------------------------------------------------

function formatDuration(seconds?: number): string {
  if (!seconds || seconds <= 0) return '';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// ---------------------------------------------------------------------------
// Sub-component: New-user welcome (upload-first CTA)
// ---------------------------------------------------------------------------

function NewUserWelcome({ onUploadVideo }: { onUploadVideo?: () => void }) {
  return (
    <div className="max-w-2xl w-full text-center">
      {/* Logo */}
      <motion.div
        variants={heroFadeIn}
        initial="initial"
        animate="animate"
        className="w-20 h-20 mx-auto mb-8 bg-gradient-to-br from-amber-500 to-orange-600 rounded-2xl flex items-center justify-center shadow-2xl shadow-amber-500/30"
      >
        <Sparkles className="w-10 h-10 text-white" />
      </motion.div>

      {/* Heading */}
      <motion.h1
        variants={heroFadeIn}
        initial="initial"
        animate="animate"
        className="text-4xl font-bold text-[var(--foreground)] mb-3"
      >
        Welcome to QPrisma
      </motion.h1>
      <motion.p
        variants={heroFadeIn}
        initial="initial"
        animate="animate"
        className="text-lg text-[var(--text-secondary)] mb-10"
      >
        Upload your first video to start exploring with AI&#8209;powered understanding
      </motion.p>

      {/* Upload drop-zone CTA */}
      <motion.button
        variants={heroFadeIn}
        initial="initial"
        animate="animate"
        onClick={onUploadVideo}
        whileHover={{ scale: 1.01 }}
        whileTap={{ scale: 0.995 }}
        className="group w-full rounded-2xl p-10 border-2 border-dashed border-[var(--border)] hover:border-[var(--amber-6)] bg-[var(--surface)] hover:bg-[var(--amber-1)] transition-all duration-300 cursor-pointer mb-10"
      >
        <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-gray-100 to-gray-200 group-hover:from-amber-100 group-hover:to-orange-100 flex items-center justify-center transition-colors duration-300">
          <Upload className="w-8 h-8 text-[var(--text-tertiary)] group-hover:text-amber-600 transition-colors duration-300" />
        </div>
        <p className="text-base font-semibold text-[var(--foreground)] mb-1">
          Drop your video here or click to browse
        </p>
        <p className="text-sm text-[var(--text-tertiary)]">
          Supports MP4, MOV, AVI, WebM
        </p>
      </motion.button>

      {/* Feature cards */}
      <motion.div
        variants={staggerSlow}
        initial="initial"
        animate="animate"
        className="grid grid-cols-1 sm:grid-cols-3 gap-4"
      >
        {FEATURES.map((f) => (
          <motion.div
            key={f.title}
            variants={staggerItem}
            className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface)] p-5 text-left"
          >
            <div
              className={`w-10 h-10 rounded-xl bg-gradient-to-br ${f.accentBg} flex items-center justify-center mb-3`}
            >
              <f.icon className={`w-5 h-5 ${f.iconColor}`} />
            </div>
            <h3 className="text-sm font-semibold text-[var(--foreground)] mb-1">{f.title}</h3>
            <p className="text-xs text-[var(--text-tertiary)] leading-relaxed">{f.description}</p>
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Video thumbnail card
// ---------------------------------------------------------------------------

function VideoCard({ video, onClick }: { video: MediaItem; onClick: () => void }) {
  const duration = formatDuration(video.duration);
  const title = video.name || video.original_filename || 'Untitled';

  return (
    <motion.button
      variants={staggerItem}
      onClick={onClick}
      whileHover={{ y: -3, transition: { duration: 0.2 } }}
      className="group rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface)] p-4 text-left hover:border-[var(--amber-5)] hover:shadow-md transition-all duration-200 min-w-0"
    >
      <div className="w-full aspect-video rounded-xl bg-gradient-to-br from-gray-100 to-gray-200 flex items-center justify-center mb-3 overflow-hidden">
        <Film className="w-8 h-8 text-[var(--text-tertiary)] group-hover:text-amber-600 transition-colors" />
      </div>
      <p className="text-sm font-medium text-[var(--foreground)] truncate" title={title}>
        {title}
      </p>
      {duration && (
        <p className="flex items-center gap-1 text-xs text-[var(--text-tertiary)] mt-1">
          <Clock className="w-3 h-3" />
          {duration}
        </p>
      )}
    </motion.button>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Returning-user dashboard
// ---------------------------------------------------------------------------

function ReturningUserWelcome({
  userName,
  videoCount,
  recentVideos,
  onUploadVideo,
  onBrowseLibrary,
  onSelectVideo,
}: {
  userName?: string;
  videoCount: number;
  recentVideos: MediaItem[];
  onUploadVideo?: () => void;
  onBrowseLibrary?: () => void;
  onSelectVideo?: (videoId: string) => void;
}) {
  const router = useRouter();
  const firstName = userName ? userName.split(' ')[0] : null;

  const handleVideoClick = (videoId: string) => {
    if (onSelectVideo) {
      onSelectVideo(videoId);
    } else {
      router.push(`/chat?videoId=${videoId}`);
    }
  };

  return (
    <div className="max-w-2xl w-full">
      {/* Greeting */}
      <motion.div
        variants={heroFadeIn}
        initial="initial"
        animate="animate"
        className="text-center mb-10"
      >
        <h1 className="text-4xl font-bold text-[var(--foreground)] mb-2">
          {firstName ? `Welcome back, ${firstName}!` : 'Welcome back!'}
        </h1>
        <p className="text-[var(--text-secondary)]">
          You have{' '}
          <span className="font-semibold text-[var(--foreground)]">{videoCount}</span>{' '}
          {videoCount === 1 ? 'video' : 'videos'} analyzed
        </p>
      </motion.div>

      {/* Recent Videos */}
      {recentVideos.length > 0 && (
        <motion.div
          variants={heroFadeIn}
          initial="initial"
          animate="animate"
          className="mb-10"
        >
          <h2 className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wider mb-4">
            Recent Videos
          </h2>
          <motion.div
            variants={staggerContainer}
            initial="initial"
            animate="animate"
            className="grid grid-cols-2 sm:grid-cols-4 gap-3"
          >
            {recentVideos.map((video) => (
              <VideoCard
                key={video.id}
                video={video}
                onClick={() => handleVideoClick(video.id)}
              />
            ))}
          </motion.div>
        </motion.div>
      )}

      {/* Quick Actions */}
      <motion.div variants={heroFadeIn} initial="initial" animate="animate">
        <h2 className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wider mb-4">
          Quick Actions
        </h2>
        <motion.div
          variants={staggerSlow}
          initial="initial"
          animate="animate"
          className="flex flex-col gap-2"
        >
          <QuickAction
            icon={Upload}
            label="Upload new video"
            onClick={onUploadVideo}
          />
          <QuickAction
            icon={Library}
            label="Browse library"
            onClick={onBrowseLibrary}
          />
          <QuickAction
            icon={GitCompareArrows}
            label="Compare videos"
            onClick={() => router.push('/compare')}
          />
        </motion.div>
      </motion.div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quick-action row
// ---------------------------------------------------------------------------

function QuickAction({
  icon: Icon,
  label,
  onClick,
}: {
  icon: React.ElementType;
  label: string;
  onClick?: () => void;
}) {
  return (
    <motion.button
      variants={staggerItem}
      onClick={onClick}
      whileHover={{ x: 4, transition: { duration: 0.15 } }}
      className="group flex items-center gap-3 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface)] px-4 py-3 text-left hover:border-[var(--amber-5)] hover:bg-[var(--amber-1)] transition-all duration-200"
    >
      <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-gray-100 to-gray-200 group-hover:from-amber-100 group-hover:to-orange-100 flex items-center justify-center transition-colors">
        <Icon className="w-4 h-4 text-[var(--text-tertiary)] group-hover:text-amber-600 transition-colors" />
      </div>
      <span className="text-sm font-medium text-[var(--foreground)] flex-1">{label}</span>
      <ArrowRight className="w-4 h-4 text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity" />
    </motion.button>
  );
}

// ---------------------------------------------------------------------------
// Main WelcomeScreen
// ---------------------------------------------------------------------------

function WelcomeScreen({
  onUploadVideo,
  onBrowseLibrary,
  onSelectVideo,
  mode = 'single',
  userName,
}: WelcomeScreenProps) {
  const { hasVideos, videoCount, recentVideos, isLoading } = useUserVideos();

  // While loading, show a subtle skeleton (avoids layout flash)
  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-10 h-10 rounded-xl bg-[var(--surface-elevated)] animate-pulse" />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto">
      {hasVideos ? (
        <ReturningUserWelcome
          userName={userName}
          videoCount={videoCount}
          recentVideos={recentVideos}
          onUploadVideo={onUploadVideo}
          onBrowseLibrary={onBrowseLibrary}
          onSelectVideo={onSelectVideo}
        />
      ) : (
        <NewUserWelcome onUploadVideo={onUploadVideo} />
      )}
    </div>
  );
}

export default memo(WelcomeScreen);
