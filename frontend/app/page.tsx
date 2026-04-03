'use client';

import { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  Sparkles, Upload, Library, MessageSquare,
  Zap, Clock, Play, Film, GitCompare,
  ArrowRight, Video, TrendingUp,
} from 'lucide-react';
import RequireAuth from '@/components/RequireAuth';
import { useAuth } from '@/contexts/AuthContext';
import { apiClient, type MediaItem } from '@/lib/api';
import { staggerContainer, staggerItem, fadeIn } from '@/lib/animations';
import ThemeToggle from '@/components/ui/ThemeToggle';

function formatDuration(seconds?: number): string {
  if (!seconds) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatTotalDuration(totalSeconds: number): string {
  if (totalSeconds < 60) return `${Math.round(totalSeconds)}s`;
  if (totalSeconds < 3600) return `${Math.round(totalSeconds / 60)}m`;
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.round((totalSeconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function DashboardContent() {
  const router = useRouter();
  const { user, logout } = useAuth();
  const [videos, setVideos] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient.getMedia()
      .then((res) => setVideos(res.media || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const stats = useMemo(() => {
    const total = videos.length;
    const processed = videos.filter(
      (v) => v.processing_status === 'completed' || v.processed,
    ).length;
    const totalDuration = videos.reduce((sum, v) => sum + (v.duration || 0), 0);
    return { total, processed, totalDuration };
  }, [videos]);

  const recentVideos = useMemo(
    () =>
      [...videos]
        .sort(
          (a, b) =>
            new Date(b.uploaded_at || 0).getTime() -
            new Date(a.uploaded_at || 0).getTime(),
        )
        .slice(0, 6),
    [videos],
  );

  const firstName = user?.full_name?.split(' ')[0];
  const greeting = firstName ? `Welcome back, ${firstName}` : 'Welcome to QPrisma';

  const QUICK_ACTIONS = [
    {
      title: 'Start Chat',
      desc: 'Chat about your videos with AI',
      icon: MessageSquare,
      gradient: 'from-indigo-500 to-purple-600',
      shadow: 'shadow-indigo-500/25',
      route: '/chat',
    },
    {
      title: 'Upload Video',
      desc: 'Add new videos for analysis',
      icon: Upload,
      gradient: 'from-amber-500 to-orange-500',
      shadow: 'shadow-amber-500/25',
      route: '/upload',
    },
    {
      title: 'My Library',
      desc: 'Browse your processed videos',
      icon: Library,
      gradient: 'from-blue-500 to-cyan-500',
      shadow: 'shadow-blue-500/25',
      route: '/library',
    },
    {
      title: 'Compare',
      desc: 'Compare videos side by side',
      icon: GitCompare,
      gradient: 'from-emerald-500 to-teal-500',
      shadow: 'shadow-emerald-500/25',
      route: '/compare',
    },
  ] as const;

  return (
    <div className="min-h-screen bg-[var(--background)] relative overflow-hidden">
      {/* Background decorations */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute -top-40 -right-40 w-[500px] h-[500px] bg-gradient-to-br from-indigo-200/50 to-purple-200/50 rounded-full blur-[100px] dark:from-indigo-900/30 dark:to-purple-900/30" />
        <div className="absolute top-1/3 -left-40 w-[400px] h-[400px] bg-gradient-to-br from-amber-200/40 to-orange-200/40 rounded-full blur-[100px] dark:from-amber-900/20 dark:to-orange-900/20" />
        <div className="absolute -bottom-40 right-1/3 w-[500px] h-[500px] bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-[100px] dark:from-blue-900/15 dark:to-cyan-900/15" />
      </div>

      {/* Top Navigation */}
      <header className="relative z-10 flex items-center justify-between px-6 py-4 lg:px-10">
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-br from-indigo-500 to-purple-600 w-10 h-10 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-500/30">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <span className="text-xl font-bold text-[var(--foreground)]">QPrisma</span>
        </div>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[var(--surface)]/80 backdrop-blur-sm border border-[var(--border-subtle)]">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-xs font-bold text-white">
              {user?.email?.substring(0, 2).toUpperCase() || 'U'}
            </div>
            <span className="text-sm font-medium text-[var(--foreground)] hidden sm:block">
              {user?.full_name || user?.email || 'User'}
            </span>
          </div>
          <button
            onClick={() => { logout(); router.push('/auth'); }}
            className="px-3 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--foreground)] transition-colors"
          >
            Sign Out
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main className="relative z-10 max-w-6xl mx-auto px-6 lg:px-10 pb-16">
        {/* Hero */}
        <motion.section
          variants={staggerContainer}
          initial="initial"
          animate="animate"
          className="text-center pt-8 pb-12"
        >
          <motion.div variants={staggerItem}>
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-[var(--surface)] border border-[var(--border-subtle)] shadow-[var(--shadow-sm)] mb-6">
              <Sparkles className="w-4 h-4 text-indigo-500" />
              <span className="text-sm font-medium text-[var(--text-secondary)]">
                AI-Powered Video Intelligence
              </span>
            </div>
          </motion.div>

          <motion.h1
            variants={staggerItem}
            className="text-4xl md:text-5xl font-bold text-[var(--foreground)] tracking-tight mb-3"
          >
            {greeting}
          </motion.h1>
          <motion.p
            variants={staggerItem}
            className="text-lg text-[var(--text-secondary)] max-w-xl mx-auto"
          >
            Unlock intelligent insights from your video content with AI-powered
            analysis, chat, and knowledge graphs.
          </motion.p>
        </motion.section>

        {/* Stats */}
        {!loading && videos.length > 0 && (
          <motion.section
            variants={staggerContainer}
            initial="initial"
            animate="animate"
            className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10"
          >
            {[
              {
                label: 'Total Videos',
                value: stats.total,
                icon: Film,
                bg: 'bg-indigo-100 dark:bg-indigo-500/20',
                fg: 'text-indigo-600 dark:text-indigo-400',
              },
              {
                label: 'Processed',
                value: stats.processed,
                icon: TrendingUp,
                bg: 'bg-[var(--sage-2)]',
                fg: 'text-[var(--sage-8)]',
              },
              {
                label: 'Total Duration',
                value: formatTotalDuration(stats.totalDuration),
                icon: Clock,
                bg: 'bg-[var(--amber-2)]',
                fg: 'text-[var(--amber-8)]',
              },
            ].map((stat) => (
              <motion.div
                key={stat.label}
                variants={staggerItem}
                className="bg-[var(--surface)]/80 backdrop-blur-sm rounded-2xl border border-[var(--border-subtle)] p-5 shadow-[var(--shadow-sm)] hover:shadow-[var(--shadow-md)] transition-shadow"
              >
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-3 ${stat.bg}`}>
                  <stat.icon className={`w-5 h-5 ${stat.fg}`} />
                </div>
                <p className="text-2xl font-bold text-[var(--foreground)]">{stat.value}</p>
                <p className="text-sm text-[var(--text-secondary)]">{stat.label}</p>
              </motion.div>
            ))}
          </motion.section>
        )}

        {/* Quick Actions */}
        <motion.section
          variants={staggerContainer}
          initial="initial"
          animate="animate"
          className="mb-10"
        >
          <motion.h2
            variants={staggerItem}
            className="text-lg font-semibold text-[var(--foreground)] mb-4"
          >
            Quick Actions
          </motion.h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {QUICK_ACTIONS.map((action) => (
              <motion.button
                key={action.title}
                variants={staggerItem}
                whileHover={{ y: -4, transition: { duration: 0.2 } }}
                whileTap={{ scale: 0.98 }}
                onClick={() => router.push(action.route)}
                className="group bg-[var(--surface)]/80 backdrop-blur-sm rounded-2xl border border-[var(--border-subtle)] p-6 text-left shadow-[var(--shadow-sm)] hover:shadow-[var(--shadow-lg)] transition-all"
              >
                <div
                  className={`w-12 h-12 rounded-xl bg-gradient-to-br ${action.gradient} flex items-center justify-center mb-4 shadow-lg ${action.shadow}`}
                >
                  <action.icon className="w-6 h-6 text-white" />
                </div>
                <h3 className="text-base font-semibold text-[var(--foreground)] mb-1 flex items-center gap-2">
                  {action.title}
                  <ArrowRight className="w-4 h-4 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all text-[var(--text-tertiary)]" />
                </h3>
                <p className="text-sm text-[var(--text-secondary)]">{action.desc}</p>
              </motion.button>
            ))}
          </div>
        </motion.section>

        {/* Recent Videos */}
        {!loading && recentVideos.length > 0 && (
          <motion.section
            variants={staggerContainer}
            initial="initial"
            animate="animate"
          >
            <motion.div
              variants={staggerItem}
              className="flex items-center justify-between mb-4"
            >
              <h2 className="text-lg font-semibold text-[var(--foreground)]">
                Recent Videos
              </h2>
              <button
                onClick={() => router.push('/library')}
                className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
              >
                View all <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </motion.div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {recentVideos.map((video) => (
                <motion.button
                  key={video.id}
                  variants={staggerItem}
                  whileHover={{ y: -2, transition: { duration: 0.2 } }}
                  onClick={() => router.push(`/chat?videoId=${video.id}`)}
                  className="group bg-[var(--surface)]/80 backdrop-blur-sm rounded-2xl border border-[var(--border-subtle)] p-4 text-left shadow-[var(--shadow-sm)] hover:shadow-[var(--shadow-md)] transition-all"
                >
                  <div className="flex items-start gap-3">
                    <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-500/20 dark:to-purple-500/20 flex items-center justify-center flex-shrink-0">
                      <Play className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <h3 className="text-sm font-semibold text-[var(--foreground)] truncate">
                        {video.original_filename || video.name || 'Untitled Video'}
                      </h3>
                      <div className="flex items-center gap-2 mt-1">
                        {video.duration != null && (
                          <span className="text-xs text-[var(--text-tertiary)]">
                            {formatDuration(video.duration)}
                          </span>
                        )}
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            video.processing_status === 'completed' || video.processed
                              ? 'bg-[var(--sage-2)] text-[var(--sage-8)]'
                              : video.processing_status === 'processing'
                                ? 'bg-[var(--amber-2)] text-[var(--amber-8)]'
                                : 'bg-[var(--surface-elevated)] text-[var(--text-tertiary)]'
                          }`}
                        >
                          {video.processing_status === 'completed' || video.processed
                            ? 'Ready'
                            : video.processing_status || 'Pending'}
                        </span>
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4 text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 mt-1" />
                  </div>
                </motion.button>
              ))}
            </div>
          </motion.section>
        )}

        {/* Empty State */}
        {!loading && videos.length === 0 && (
          <motion.section
            variants={fadeIn}
            initial="initial"
            animate="animate"
            className="text-center py-16"
          >
            <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-500/20 dark:to-purple-500/20 rounded-2xl flex items-center justify-center">
              <Video className="w-10 h-10 text-indigo-500 dark:text-indigo-400" />
            </div>
            <h3 className="text-xl font-semibold text-[var(--foreground)] mb-2">
              No videos yet
            </h3>
            <p className="text-[var(--text-secondary)] mb-6 max-w-md mx-auto">
              Upload your first video to get started with AI-powered analysis, chat,
              and knowledge graphs.
            </p>
            <button
              onClick={() => router.push('/upload')}
              className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-indigo-500 to-purple-600 text-white rounded-xl font-semibold shadow-lg shadow-indigo-500/30 hover:from-indigo-600 hover:to-purple-700 transition-colors"
            >
              <Upload className="w-5 h-5" />
              Upload Your First Video
            </button>
          </motion.section>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 animate-pulse">
            {[1, 2, 3].map((i) => (
              <div key={i} className="bg-[var(--surface-elevated)] rounded-2xl h-24" />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

export default function Home() {
  return (
    <RequireAuth>
      <DashboardContent />
    </RequireAuth>
  );
}
