'use client';

import React from 'react';
import {
  Scissors,
  Sparkles,
  Search,
  Subtitles,
  Download,
  Wrench,
  Loader2,
  CheckCircle2,
  XCircle,
  Terminal,
  ArrowRightCircle,
} from 'lucide-react';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolCalls?: number;
}

interface ToolStatus {
  name: string;
  status: 'running' | 'success' | 'error';
}

interface QuickAction {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  message: string;
}

const QUICK_ACTIONS: QuickAction[] = [
  { icon: Sparkles, label: 'Generate viral clips', message: 'Generate 5 viral clips from this video' },
  { icon: Search, label: 'Find highlights', message: 'Find the most engaging moments' },
  { icon: Subtitles, label: 'Add subtitles', message: 'Add subtitles to all clips with hormozi style' },
  { icon: Download, label: 'Export all', message: 'Export all clips for TikTok' },
];

interface EditorChatMessagesProps {
  messages: ChatMessage[];
  streamingContent: string;
  activeTools: ToolStatus[];
  isLoading: boolean;
  onQuickAction: (message: string) => void;
  onTimestampClick?: (timestamp: number) => void;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
}

export function EditorChatMessages({
  messages,
  streamingContent,
  activeTools,
  isLoading,
  onQuickAction,
  onTimestampClick,
  messagesEndRef,
}: EditorChatMessagesProps) {
  const hasMessages = messages.length > 0;

  const renderMessageContent = (content: string) => {
    let displayContent = content;
    let suggestions: string[] = [];

    const suggestionSplit = content.split('---SUGGESTED_QUESTIONS---');
    if (suggestionSplit.length > 1) {
      displayContent = suggestionSplit[0].trim();
      suggestions = suggestionSplit[1].trim()
        .split('\n')
        .map(s => s.trim())
        .filter(s => s.length > 0 && s.includes('?'));
    }

    const timestampRegex = /\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?/g;
    const parts: (string | React.ReactNode)[] = [];
    let lastIndex = 0;
    let match;

    while ((match = timestampRegex.exec(displayContent)) !== null) {
      if (match.index > lastIndex) {
        parts.push(displayContent.slice(lastIndex, match.index));
      }
      const hours = match[3] ? parseInt(match[1]) : 0;
      const minutes = match[3] ? parseInt(match[2]) : parseInt(match[1]);
      const seconds = match[3] ? parseInt(match[3]) : parseInt(match[2]);
      const totalSeconds = hours * 3600 + minutes * 60 + seconds;

      parts.push(
        <button
          key={match.index}
          onClick={() => onTimestampClick?.(totalSeconds)}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded text-sm font-medium hover:bg-indigo-200 transition-colors"
        >
          {match[0]}
        </button>
      );
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < displayContent.length) {
      parts.push(displayContent.slice(lastIndex));
    }

    return (
      <>
        {parts.length > 0 ? parts : displayContent}
        {suggestions.length > 0 && (
          <div className="mt-4 pt-3 border-t border-gray-200/50 flex flex-col gap-2">
            <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">Suggested Follow-ups</p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((suggestion, idx) => (
                <button
                  key={idx}
                  onClick={() => onQuickAction(suggestion)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white text-indigo-700 hover:bg-indigo-50 hover:text-indigo-800 rounded-full text-sm transition-colors border border-gray-200 text-left shadow-sm"
                >
                  <span className="flex-1">{suggestion}</span>
                  <ArrowRightCircle className="w-4 h-4 opacity-50" />
                </button>
              ))}
            </div>
          </div>
        )}
      </>
    );
  };

  if (!hasMessages) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <div className="w-16 h-16 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center mb-4 shadow-lg">
          <Scissors className="w-8 h-8 text-white" />
        </div>
        <h2 className="text-xl font-bold text-gray-900 mb-2">Chat-to-Edit</h2>
        <p className="text-gray-500 mb-6 max-w-md">
          Tell me what you want to do with your video. Search for moments,
          create clips, add subtitles, and export for any platform.
        </p>
        <div className="grid grid-cols-2 gap-2 w-full max-w-md">
          {QUICK_ACTIONS.map((action, i) => (
            <button
              key={i}
              onClick={() => onQuickAction(action.message)}
              className="flex items-center gap-2 p-3 bg-white border border-gray-200 rounded-xl hover:border-indigo-300 hover:bg-indigo-50 transition-all text-left"
            >
              <action.icon className="w-5 h-5 text-indigo-500 flex-shrink-0" />
              <span className="text-sm text-gray-700">{action.label}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      {messages.map((message) => (
        <div
          key={message.id}
          className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
        >
          <div
            className={`max-w-[85%] rounded-2xl px-4 py-3 ${
              message.role === 'user'
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-100 text-gray-900'
            }`}
          >
            <div className="text-sm whitespace-pre-wrap">
              {message.role === 'assistant'
                ? renderMessageContent(message.content)
                : message.content}
            </div>
            {message.toolCalls && (
              <div className="mt-2 pt-2 border-t border-gray-200/50">
                <span className="text-xs text-gray-500 flex items-center gap-1">
                  <Wrench className="w-3 h-3" />
                  {message.toolCalls} tool{message.toolCalls > 1 ? 's' : ''} used
                </span>
              </div>
            )}
          </div>
        </div>
      ))}

      {/* Active Tools */}
      {activeTools.length > 0 && (
        <div className="flex justify-start animate-in slide-in-from-bottom-2 duration-300">
          <div className="max-w-[85%] w-full">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-7 h-7 rounded-lg bg-gray-100 flex items-center justify-center border border-gray-200">
                <Wrench className="w-3.5 h-3.5 text-gray-500" />
              </div>
              <span className="text-sm font-medium text-gray-500">Agent Tools</span>
            </div>
            <div className="ml-9 flex flex-col gap-2 mb-4 w-full">
              <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase tracking-wider mb-1 px-1">
                <Terminal className="w-3 h-3" />
                Process Log
              </div>
              <div className="space-y-2">
                {activeTools.map((tool, idx) => (
                  <div
                    key={idx}
                    className={`flex items-center gap-2.5 p-3 rounded-lg border text-sm transition-all duration-300 animate-in slide-in-from-left-2 ${
                      tool.status === 'running'
                        ? 'bg-blue-50/50 border-blue-100 text-blue-700'
                        : tool.status === 'success'
                        ? 'bg-green-50/50 border-green-100 text-green-700'
                        : 'bg-red-50/50 border-red-100 text-red-700'
                    }`}
                  >
                    <div className={`flex-shrink-0 ${tool.status === 'running' ? 'animate-spin' : ''}`}>
                      {tool.status === 'running' && <Loader2 className="w-4 h-4" />}
                      {tool.status === 'success' && <CheckCircle2 className="w-4 h-4" />}
                      {tool.status === 'error' && <XCircle className="w-4 h-4" />}
                    </div>
                    <div className="flex flex-col">
                      <span className="font-medium">{tool.name.replace(/_/g, ' ')}</span>
                      <span className="text-xs opacity-80">
                        {tool.status === 'running' ? 'Executing...' : tool.status === 'success' ? 'Completed' : 'Failed'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Streaming content */}
      {streamingContent && (
        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-2xl px-4 py-3 bg-gray-100 text-gray-900">
            <div className="text-sm whitespace-pre-wrap">
              {renderMessageContent(streamingContent)}
            </div>
          </div>
        </div>
      )}

      {/* Loading indicator */}
      {isLoading && !streamingContent && activeTools.length === 0 && (
        <div className="flex justify-start">
          <div className="bg-gray-100 rounded-2xl px-4 py-3">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce" />
              <div className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce [animation-delay:0.2s]" />
              <div className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce [animation-delay:0.4s]" />
            </div>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
}
