'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import RequireAuth from '@/components/RequireAuth';

/**
 * Home page - redirects to the new chat interface.
 * The new UI uses a chat-centric approach inspired by Vimo.
 */
export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/chat');
  }, [router]);

  return (
    <RequireAuth>
      <main className="min-h-screen flex items-center justify-center bg-[var(--background)] relative overflow-hidden">
        {/* Warm gradient overlays */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-32 -right-32 w-96 h-96 bg-[var(--violet-3)] rounded-full blur-[120px] opacity-40" />
          <div className="absolute -bottom-32 -left-32 w-96 h-96 bg-[var(--violet-2)] rounded-full blur-[120px] opacity-50" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-[var(--violet-1)] rounded-full blur-[160px] opacity-30" />
        </div>

        <div className="relative z-10 text-center" style={{ animation: 'scaleIn 0.5s var(--easing-default) both' }}>
          {/* Logo mark */}
          <div className="mx-auto mb-6 w-16 h-16 rounded-[var(--radius-2xl)] bg-[var(--surface)] shadow-[var(--shadow-lg)] border border-[var(--border-subtle)] flex items-center justify-center">
            <svg className="w-8 h-8 text-[var(--violet-8)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="23 7 16 12 23 17 23 7" />
              <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
            </svg>
          </div>

          <h1 className="text-2xl font-semibold text-[var(--foreground)] tracking-tight mb-2">
            QPrisma
          </h1>
          <p className="text-[var(--text-secondary)] text-sm mb-8">
            Intelligent multimedia processing
          </p>

          {/* Violet spinner */}
          <div className="w-8 h-8 border-[3px] border-[var(--violet-3)] border-t-[var(--violet-8)] rounded-full animate-spin mx-auto mb-3" />
          <p className="text-[var(--text-tertiary)] text-xs">
            Loading your workspace…
          </p>
        </div>
      </main>
    </RequireAuth>
  );
}
