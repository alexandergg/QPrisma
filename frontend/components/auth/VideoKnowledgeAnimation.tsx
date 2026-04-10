'use client';

import { useId } from 'react';

/**
 * Video Knowledge Network — decorative SVG animation for the auth hero panel.
 *
 * Combines floating video-frame rectangles, knowledge-graph connections,
 * pulsing nodes, and an AI scan beam.  CSS-only animation (no requestAnimationFrame) —
 * all motion uses compositor-friendly CSS keyframes.
 */
export default function VideoKnowledgeAnimation() {
  const gradientId = useId();
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 600 700"
        preserveAspectRatio="xMidYMid slice"
        fill="none"
      >
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="transparent" />
            <stop offset="20%" stopColor="rgba(167,139,250,0.3)" />
            <stop offset="50%" stopColor="rgba(139,92,246,0.5)" />
            <stop offset="80%" stopColor="rgba(167,139,250,0.3)" />
            <stop offset="100%" stopColor="transparent" />
          </linearGradient>
        </defs>

        {/* ── Video frames ── */}
        <rect className="vk-frame-a" x="50" y="80" width="200" height="120" rx="8"
          fill="rgba(167,139,250,0.03)" stroke="rgba(167,139,250,0.12)" strokeWidth="1" />
        <polygon className="vk-frame-a" points="135,130 135,150 152,140"
          fill="rgba(167,139,250,0.08)" />

        <rect className="vk-frame-b" x="310" y="240" width="170" height="100" rx="7"
          fill="rgba(167,139,250,0.025)" stroke="rgba(167,139,250,0.10)" strokeWidth="1" />
        <polygon className="vk-frame-b" points="380,280 380,300 397,290"
          fill="rgba(167,139,250,0.06)" />

        <rect className="vk-frame-c" x="80" y="400" width="185" height="112" rx="7"
          fill="rgba(167,139,250,0.03)" stroke="rgba(167,139,250,0.11)" strokeWidth="1" />
        <polygon className="vk-frame-c" points="157,446 157,466 174,456"
          fill="rgba(167,139,250,0.07)" />

        <rect className="vk-frame-a" x="350" y="480" width="145" height="88" rx="6"
          fill="rgba(167,139,250,0.02)" stroke="rgba(167,139,250,0.08)" strokeWidth="1"
          style={{ animationDelay: '3s' }} />

        {/* ── Knowledge graph connections ── */}
        <line className="vk-line" x1="150" y1="200" x2="395" y2="240"
          stroke="rgba(167,139,250,0.15)" strokeWidth="1" />
        <line className="vk-line" x1="395" y1="340" x2="172" y2="400"
          stroke="rgba(167,139,250,0.12)" strokeWidth="1"
          style={{ animationDelay: '1.5s' }} />
        <line className="vk-line" x1="250" y1="140" x2="395" y2="280"
          stroke="rgba(167,139,250,0.10)" strokeWidth="1"
          style={{ animationDelay: '3s' }} />
        <line className="vk-line" x1="265" y1="456" x2="350" y2="520"
          stroke="rgba(167,139,250,0.13)" strokeWidth="1"
          style={{ animationDelay: '2s' }} />
        <line className="vk-line" x1="480" y1="290" x2="422" y2="480"
          stroke="rgba(167,139,250,0.09)" strokeWidth="1"
          style={{ animationDelay: '4s' }} />

        {/* ── Knowledge nodes ── */}
        <circle className="vk-node" cx="150" cy="200" r="4" fill="#A78BFA" />
        <circle className="vk-node" cx="395" cy="240" r="3.5" fill="#A78BFA"
          style={{ animationDelay: '0.8s' }} />
        <circle className="vk-node" cx="395" cy="340" r="3" fill="#8B5CF6"
          style={{ animationDelay: '1.6s' }} />
        <circle className="vk-node" cx="172" cy="400" r="4" fill="#A78BFA"
          style={{ animationDelay: '2.4s' }} />
        <circle className="vk-node" cx="250" cy="140" r="3" fill="#8B5CF6"
          style={{ animationDelay: '0.4s' }} />
        <circle className="vk-node" cx="265" cy="456" r="3.5" fill="#A78BFA"
          style={{ animationDelay: '1.2s' }} />
        <circle className="vk-node" cx="422" cy="480" r="3" fill="#8B5CF6"
          style={{ animationDelay: '2s' }} />
        <circle className="vk-node" cx="480" cy="290" r="3.5" fill="#A78BFA"
          style={{ animationDelay: '2.8s' }} />

        {/* ── AI scan beam ── */}
        <rect className="vk-scan" x="0" y="-3" width="600" height="3" rx="1.5"
          fill={`url(#${gradientId})`} />
      </svg>
    </div>
  );
}
