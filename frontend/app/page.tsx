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
    // Redirect to the new chat interface
    router.replace('/chat');
  }, [router]);

  return (
    <RequireAuth>
      <main className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-white to-indigo-50/30">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-gray-500">Loading QPrisma...</p>
        </div>
      </main>
    </RequireAuth>
  );
}
