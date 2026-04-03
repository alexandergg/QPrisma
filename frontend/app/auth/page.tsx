'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';

export default function AuthPage() {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const { login, isAuthenticated } = useAuth();
  const router = useRouter();

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      router.push('/');
    }
  }, [isAuthenticated, router]);

  const handleLogin = async () => {
    setError('');
    setLoading(true);
    try {
      await login();
      // Don't navigate here — the useEffect above will redirect to '/'
      // once isAuthenticated becomes true after the user profile is fetched.
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-1 via-[var(--surface)] to-[var(--background)] flex items-center justify-center p-4">
      <div className="w-full max-w-md px-2 sm:px-0">
        {/* Logo */}
        <div className="text-center mb-6 md:mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 md:w-16 md:h-16 bg-gradient-to-br from-amber-9 to-amber-10 rounded-[var(--radius-2xl)] mb-4 shadow-[var(--shadow-lg)]">
            <svg
              className="w-8 h-8 text-white"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
              />
            </svg>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold text-[var(--foreground)]">QPrisma</h1>
          <p className="text-[var(--sage-9)] mt-2">AI-Powered Video Analysis</p>
        </div>

        {/* Auth Card */}
        <div className="bg-[var(--surface)] rounded-[var(--radius-2xl)] shadow-[var(--shadow-xl)] p-6 md:p-8">
          <div className="text-center mb-6">
            <h2 className="text-xl font-semibold text-[var(--foreground)]">Welcome</h2>
            <p className="text-[var(--sage-8)] mt-1">Sign in with your organization account</p>
          </div>

          {error && (
            <div className="bg-rose-3 border border-rose-5 text-rose-11 px-4 py-3 rounded-[var(--radius-lg)] mb-4">
              {error}
            </div>
          )}

          <button
            onClick={handleLogin}
            disabled={loading}
            className="w-full bg-gradient-to-r from-amber-9 to-amber-10 text-white py-3.5 md:py-3 rounded-[var(--radius-xl)] font-medium hover:from-amber-10 hover:to-amber-11 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-[var(--shadow-lg)] flex items-center justify-center gap-3 min-h-[44px]"
          >
            {loading ? (
              <span className="flex items-center justify-center">
                <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Signing in...
              </span>
            ) : (
              <>
                <svg className="w-5 h-5" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
                  <rect x="1" y="1" width="9" height="9" fill="#f25022" />
                  <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
                  <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
                  <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
                </svg>
                Sign in with Microsoft
              </>
            )}
          </button>
        </div>

        {/* Footer */}
        <p className="text-center text-[var(--sage-8)] text-sm mt-6">
          Powered by Azure AI Foundry & Computer Vision
        </p>
      </div>
    </div>
  );
}
