'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { Sparkles, Brain, Zap } from 'lucide-react';

/* ── Static data ───────────────────────────────────────────────── */

const features = [
  { Icon: Sparkles, title: 'AI Video Analysis', desc: 'Understand every frame, word, and concept' },
  { Icon: Brain, title: 'Natural Language Search', desc: 'Ask anything about your videos' },
  { Icon: Zap, title: 'Knowledge Graphs', desc: 'See connections across your content' },
];

const particles = [
  { top: '8%', left: '15%', size: 3, delay: 0 },
  { top: '22%', left: '78%', size: 2, delay: 1.2 },
  { top: '35%', left: '42%', size: 2.5, delay: 0.6 },
  { top: '52%', left: '88%', size: 2, delay: 2.1 },
  { top: '65%', left: '25%', size: 3, delay: 1.8 },
  { top: '78%', left: '62%', size: 2, delay: 0.3 },
  { top: '88%', left: '35%', size: 2.5, delay: 2.5 },
  { top: '15%', left: '55%', size: 2, delay: 1.5 },
  { top: '45%', left: '12%', size: 3, delay: 0.9 },
  { top: '72%', left: '92%', size: 2, delay: 1.1 },
  { top: '30%', left: '68%', size: 2, delay: 2.8 },
  { top: '92%', left: '78%', size: 2.5, delay: 0.4 },
];

/* ── SVG Icons (inline, no external deps) ──────────────────────── */

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
    </svg>
  );
}

function MicrosoftIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 21 21">
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  );
}

/* ── Shared input class ────────────────────────────────────────── */

const inputClass =
  'w-full px-4 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-lg)] text-[var(--foreground)] placeholder:text-[var(--text-tertiary)] focus:ring-2 focus:ring-[var(--violet-6)]/50 focus:border-[var(--violet-6)] outline-none transition-all duration-200';

/* ── Component ─────────────────────────────────────────────────── */

export default function AuthPage() {
  const [activeTab, setActiveTab] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const { login, isAuthenticated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isAuthenticated) {
      router.push('/');
    }
  }, [isAuthenticated, router]);

  // Authentication is handled exclusively via MSAL (Azure AD).
  // The email/password form fields are a visual placeholder that is part of
  // the cinematic login design — submitting the form triggers MSAL SSO.
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleOAuthLogin = async () => {
    setError('');
    setLoading(true);
    try {
      await login();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      {/* ─── Left Panel — Cinematic Showcase ─── */}
      <div className="relative w-full md:w-[55%] min-h-[340px] md:min-h-screen overflow-hidden flex-shrink-0">
        {/* Mesh gradient */}
        <div
          className="absolute inset-0"
          style={{
            background: 'linear-gradient(-45deg, #0C0C0A, #1a1a16, #2a2518, #0C0C0A)',
            backgroundSize: '400% 400%',
            animation: 'mesh-gradient 15s ease infinite',
          }}
        />

        {/* Subtle radial glow */}
        <div
          className="absolute inset-0 opacity-30"
          style={{
            background: 'radial-gradient(ellipse at 30% 50%, rgba(212,165,53,0.15) 0%, transparent 70%)',
          }}
        />

        {/* Particle dots */}
        <div className="absolute inset-0">
          {particles.map((p, i) => (
            <span
              key={i}
              className="absolute rounded-full bg-white/20"
              style={{
                top: p.top,
                left: p.left,
                width: p.size,
                height: p.size,
                animation: `particle-pulse 4s ease-in-out infinite`,
                animationDelay: `${p.delay}s`,
              }}
            />
          ))}
        </div>

        {/* Content */}
        <div
          className="relative z-10 flex flex-col justify-center h-full px-8 md:px-14 lg:px-20 py-12 md:py-0"
          style={{ animation: 'fade-in-up 0.8s ease-out' }}
        >
          {/* Branding */}
          <div className="mb-12 md:mb-16">
            <div className="flex items-center gap-3 mb-8">
              <div
                className="w-12 h-12 rounded-[14px] flex items-center justify-center"
                style={{
                  background: 'linear-gradient(135deg, #A78BFA, #8B5CF6)',
                  animation: 'glow-ring 4s ease-in-out infinite',
                }}
              >
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1C1B18" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="12 2 2 22 22 22" />
                  <line x1="12" y1="10" x2="12" y2="16" />
                </svg>
              </div>
              <span className="text-2xl font-bold text-white tracking-tight">QPrisma</span>
            </div>

            <h1 className="text-4xl md:text-5xl lg:text-[3.5rem] font-bold text-white leading-[1.1] tracking-tight">
              Your videos,
              <br />
              <span className="bg-gradient-to-r from-[#A78BFA] to-[#8B5CF6] bg-clip-text text-transparent">
                understood.
              </span>
            </h1>
            <p className="mt-4 text-white/50 text-lg max-w-md">
              Unlock insights from every frame with AI-powered analysis, search, and knowledge discovery.
            </p>
          </div>

          {/* Feature highlights */}
          <div className="space-y-5">
            {features.map((f, i) => (
              <div
                key={f.title}
                className="flex items-start gap-4 group"
                style={{ animation: `float 6s ease-in-out infinite`, animationDelay: `${i * 0.7}s` }}
              >
                <div className="w-10 h-10 rounded-[var(--radius-lg)] bg-white/[0.07] backdrop-blur-sm flex items-center justify-center flex-shrink-0 border border-white/[0.06] transition-colors duration-300 group-hover:bg-white/[0.12]">
                  <f.Icon className="w-[18px] h-[18px] text-[#A78BFA]" />
                </div>
                <div>
                  <h3 className="text-white font-semibold text-[15px] leading-snug">{f.title}</h3>
                  <p className="text-white/45 text-sm mt-0.5">{f.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ─── Right Panel — Auth Form ─── */}
      <div className="w-full md:w-[45%] bg-[var(--background)] flex items-center justify-center px-6 py-12 md:px-10 lg:px-16">
        <div className="w-full max-w-[420px]" style={{ animation: 'fade-in-up 0.6s ease-out 0.15s both' }}>
          {/* Header */}
          <div className="mb-8">
            <h2 className="text-[26px] font-bold text-[var(--foreground)] tracking-tight">
              {activeTab === 'login' ? 'Welcome back' : 'Get started'}
            </h2>
            <p className="text-[var(--text-secondary)] mt-1.5 text-[15px]">
              {activeTab === 'login'
                ? 'Sign in to continue to QPrisma'
                : 'Create your account to get started'}
            </p>
          </div>

          {/* OAuth buttons */}
          <div className="flex gap-3 mb-6">
            <button
              type="button"
              onClick={handleOAuthLogin}
              disabled={loading}
              className="flex-1 flex items-center justify-center gap-2 py-3 border border-[var(--border)] rounded-[var(--radius-lg)] hover:bg-[var(--surface-elevated)] active:scale-[0.98] transition-all duration-150 text-sm font-medium text-[var(--foreground)] disabled:opacity-50"
            >
              <GoogleIcon />
              Google
            </button>
            <button
              type="button"
              disabled
              title="GitHub OAuth coming soon"
              className="flex-1 flex items-center justify-center gap-2 py-3 border border-[var(--border)] rounded-[var(--radius-lg)] transition-all duration-150 text-sm font-medium text-[var(--foreground)] opacity-50 cursor-not-allowed"
            >
              <GitHubIcon />
              GitHub
            </button>
            <button
              type="button"
              onClick={handleOAuthLogin}
              disabled={loading}
              className="flex-1 flex items-center justify-center gap-2 py-3 border border-[var(--border)] rounded-[var(--radius-lg)] hover:bg-[var(--surface-elevated)] active:scale-[0.98] transition-all duration-150 text-sm font-medium text-[var(--foreground)] disabled:opacity-50"
            >
              <MicrosoftIcon />
              Microsoft
            </button>
          </div>

          {/* Divider */}
          <div className="flex items-center gap-4 mb-6">
            <div className="flex-1 h-px bg-[var(--border)]" />
            <span className="text-xs text-[var(--text-tertiary)] uppercase tracking-wider font-medium">
              or continue with
            </span>
            <div className="flex-1 h-px bg-[var(--border)]" />
          </div>

          {/* Login / Register tabs */}
          <div className="bg-[var(--surface-elevated)] rounded-[var(--radius-lg)] p-1 flex mb-6">
            <button
              type="button"
              onClick={() => { setActiveTab('login'); setError(''); }}
              className={`flex-1 py-2.5 text-sm font-medium rounded-[var(--radius-md)] transition-all duration-200 ${
                activeTab === 'login'
                  ? 'bg-[var(--surface)] text-[var(--foreground)] shadow-[var(--shadow-xs)]'
                  : 'text-[var(--text-secondary)] hover:text-[var(--foreground)]'
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => { setActiveTab('register'); setError(''); }}
              className={`flex-1 py-2.5 text-sm font-medium rounded-[var(--radius-md)] transition-all duration-200 ${
                activeTab === 'register'
                  ? 'bg-[var(--surface)] text-[var(--foreground)] shadow-[var(--shadow-xs)]'
                  : 'text-[var(--text-secondary)] hover:text-[var(--foreground)]'
              }`}
            >
              Create Account
            </button>
          </div>

          {/* Error */}
          {error && (
            <div className="bg-[var(--rose-3)]/50 border border-[var(--rose-7)]/30 text-[var(--rose-8)] px-4 py-3 rounded-[var(--radius-lg)] mb-5 text-sm flex items-start gap-2">
              <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              {error}
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {activeTab === 'register' && (
              <div>
                <label className="block text-sm font-medium text-[var(--foreground)] mb-1.5">
                  Full Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="John Doe"
                  className={inputClass}
                  autoComplete="name"
                />
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-[var(--foreground)] mb-1.5">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className={inputClass}
                autoComplete="email"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-sm font-medium text-[var(--foreground)]">
                  Password
                </label>
                {activeTab === 'login' && (
                  <button
                    type="button"
                    className="text-xs text-[var(--violet-9)] hover:text-[var(--violet-10)] font-medium transition-colors"
                  >
                    Forgot password?
                  </button>
                )}
              </div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className={inputClass}
                autoComplete={activeTab === 'login' ? 'current-password' : 'new-password'}
              />
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[var(--foreground)] text-[var(--surface)] py-3.5 rounded-[var(--radius-lg)] font-semibold hover:opacity-90 active:scale-[0.99] transition-all duration-150 shadow-[var(--shadow-md)] text-[15px] disabled:opacity-50 disabled:cursor-not-allowed mt-2"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg
                    className="animate-spin h-[18px] w-[18px]"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  {activeTab === 'login' ? 'Signing in…' : 'Creating account…'}
                </span>
              ) : (
                activeTab === 'login' ? 'Sign in with SSO' : 'Create Account with SSO'
              )}
            </button>
          </form>

          {/* Toggle prompt */}
          <p className="text-center text-sm text-[var(--text-secondary)] mt-6">
            {activeTab === 'login' ? (
              <>
                Don&apos;t have an account?{' '}
                <button
                  type="button"
                  onClick={() => { setActiveTab('register'); setError(''); }}
                  className="text-[var(--violet-9)] hover:text-[var(--violet-10)] font-semibold transition-colors"
                >
                  Sign up
                </button>
              </>
            ) : (
              <>
                Already have an account?{' '}
                <button
                  type="button"
                  onClick={() => { setActiveTab('login'); setError(''); }}
                  className="text-[var(--violet-9)] hover:text-[var(--violet-10)] font-semibold transition-colors"
                >
                  Sign in
                </button>
              </>
            )}
          </p>

          {/* Footer */}
          <p className="text-center text-[var(--text-tertiary)] text-xs mt-8">
            Powered by Azure AI &amp; OpenAI
          </p>
        </div>
      </div>
    </div>
  );
}
