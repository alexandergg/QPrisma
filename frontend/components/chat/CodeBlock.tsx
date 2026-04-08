'use client';

import React, { useState, useCallback } from 'react';
import { Check, Copy } from 'lucide-react';

/** Recursively extract plain text from React node tree. */
function extractTextContent(node: React.ReactNode): string {
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(extractTextContent).join('');
  if (React.isValidElement(node)) {
    return extractTextContent(
      (node.props as { children?: React.ReactNode }).children,
    );
  }
  return '';
}

interface CodeBlockProps {
  children: React.ReactNode;
  language?: string;
}

export default function CodeBlock({ children, language }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      const text = extractTextContent(children);
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may be unavailable */
    }
  }, [children]);

  return (
    <div className="code-block group/code relative my-4 rounded-xl overflow-hidden border border-[#313244] bg-[#1e1e2e]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-[#181825] border-b border-[#313244]">
        <span className="text-xs font-mono text-[#a6adc8] select-none">
          {language || 'code'}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 text-xs text-[#a6adc8] hover:text-white transition-colors"
          aria-label={copied ? 'Copied' : 'Copy code'}
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-green-400" />
              <span>Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      {/* Code body */}
      <div className="overflow-x-auto p-4 text-sm leading-relaxed">
        <pre className="!m-0 !p-0 !bg-transparent !border-0">{children}</pre>
      </div>
    </div>
  );
}
