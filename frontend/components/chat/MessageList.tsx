'use client';

import React, { useRef, useEffect } from 'react';
import { Sparkles, Film, Loader2, CheckCircle2, XCircle, Wrench, Terminal, ArrowRightCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import TimestampBadge from './TimestampBadge';

export interface ToolStatus {
  name: string;
  status: 'running' | 'success' | 'error';
}

export interface ChatMessageSource {
  timestamp: number;
  type: 'visual' | 'audio' | 'entity';
  description?: string;
  score?: number;
}

export interface ChatMessageData {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  sources?: ChatMessageSource[];
  isLoading?: boolean;
  videoName?: string;
  toolCalls?: number;
}

interface MessageListProps {
  messages: ChatMessageData[];
  isLoading?: boolean;
  onTimestampClick?: (timestamp: number) => void;
  onSuggestionClick?: (suggestion: string) => void;
  streamingContent?: string;
  activeTools?: ToolStatus[];
}

function ToolProgress({ tools }: { tools: ToolStatus[] }) {
  if (!tools || tools.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 mb-4 w-full">
      <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase tracking-wider mb-1 px-1">
        <Terminal className="w-3 h-3" />
        Process Log
      </div>
      <div className="space-y-2">
        {tools.map((tool, idx) => (
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
              <span className="font-medium">
                {tool.name.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')}
              </span>
              <span className="text-xs opacity-80">
                {tool.status === 'running' ? 'Executing...' : tool.status === 'success' ? 'Completed' : 'Failed'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1">
      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </div>
  );
}

function MessageBubble({
  message,
  onTimestampClick,
  onSuggestionClick,
}: {
  message: ChatMessageData;
  onTimestampClick?: (timestamp: number) => void;
  onSuggestionClick?: (suggestion: string) => void;
}) {
  const isUser = message.role === 'user';
  
  // Parse content for suggestions
  let displayContent = message.content;
  let suggestions: string[] = [];
  
  const suggestionSplit = displayContent.split('---SUGGESTED_QUESTIONS---');
  if (suggestionSplit.length > 1) {
    displayContent = suggestionSplit[0].trim();
    const suggestionsText = suggestionSplit[1].trim();
    suggestions = suggestionsText
      .split('\n')
      .map(s => s.trim())
      .filter(s => s.length > 0 && s.includes('?')); // Simple filter for questions
  }

  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-in slide-in-from-bottom-2 duration-300`}
    >
      <div className={`max-w-[85%] ${isUser ? '' : ''}`}>
        {/* Assistant avatar and label */}
        {!isUser && (
          <div className="flex items-center gap-2 mb-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/30">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <span className="text-sm font-medium text-gray-600">QPrisma</span>
          </div>
        )}

        {/* Message bubble */}
        <div
          className={`p-4 rounded-2xl ${
            isUser
              ? 'bg-gradient-to-r from-indigo-500 to-purple-600 text-white rounded-tr-md shadow-lg shadow-indigo-500/20'
              : 'bg-white text-gray-800 rounded-tl-md shadow-md border border-gray-100'
          }`}
        >
          {message.isLoading ? (
            <div className="flex items-center gap-3 py-1">
              <TypingIndicator />
              <span className="text-sm text-gray-500">Analyzing...</span>
            </div>
          ) : (
            <>
              {/* Video reference for user messages */}
              {isUser && message.videoName && (
                <div className="flex items-center gap-1.5 text-white/80 text-xs mb-2">
                  <Film className="w-3 h-3" />
                  {message.videoName}
                </div>
              )}

              {/* Message content with Markdown rendering */}
              {isUser ? (
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
              ) : (
                <div className="text-sm leading-relaxed prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-strong:text-gray-900 prose-code:text-indigo-600 prose-code:bg-indigo-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none">
                  <ReactMarkdown>{displayContent}</ReactMarkdown>
                </div>
              )}

              {/* Suggestions Chips */}
              {!isUser && suggestions.length > 0 && (
                <div className="mt-4 pt-3 border-t border-gray-100 flex flex-col gap-2">
                  <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">Suggested Follow-ups</p>
                  <div className="flex flex-wrap gap-2">
                    {suggestions.map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => onSuggestionClick?.(suggestion)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-50 text-indigo-700 hover:bg-indigo-100 hover:text-indigo-800 rounded-full text-sm transition-colors border border-indigo-100 text-left"
                      >
                        <span className="flex-1">{suggestion}</span>
                        <ArrowRightCircle className="w-4 h-4 opacity-50" />
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Sources / Timestamps */}
              {!isUser && message.sources && message.sources.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-100">
                  <p className="text-xs text-gray-400 mb-2">Referenced moments:</p>
                  <div className="flex flex-wrap gap-2">
                    {message.sources.slice(0, 5).map((source, index) => (
                      <TimestampBadge
                        key={index}
                        timestamp={source.timestamp}
                        type={source.type}
                        onClick={() => onTimestampClick?.(source.timestamp)}
                      />
                    ))}
                    {message.sources.length > 5 && (
                      <span className="text-xs text-gray-400 self-center">
                        +{message.sources.length - 5} more
                      </span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MessageList({ messages, isLoading, onTimestampClick, onSuggestionClick, streamingContent, activeTools = [] }: MessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading, streamingContent, activeTools]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            onTimestampClick={onTimestampClick}
            onSuggestionClick={onSuggestionClick}
          />
        ))}

        {/* Active Tools Display - Rendering as a distinct section in the chat stream */}
        {activeTools.length > 0 && (
           <div className="flex justify-start animate-in slide-in-from-bottom-2 duration-300">
             <div className="max-w-[85%] w-full">
               <div className="flex items-center gap-2 mb-2">
                 <div className="w-7 h-7 rounded-lg bg-gray-100 flex items-center justify-center border border-gray-200">
                   <Wrench className="w-3.5 h-3.5 text-gray-500" />
                 </div>
                 <span className="text-sm font-medium text-gray-500">Agent Tools</span>
               </div>
               
               <div className="ml-9">
                 <ToolProgress tools={activeTools} />
               </div>
             </div>
           </div>
        )}

        {/* Streaming response */}
        {streamingContent && (
          <MessageBubble
            message={{
              id: 'streaming',
              role: 'assistant',
              content: streamingContent,
              timestamp: new Date(),
            }}
          />
        )}

        {/* Loading indicator for pending response (only if not streaming and not showing tools) */}
        {isLoading && !streamingContent && activeTools.length === 0 && (
          <MessageBubble
            message={{
              id: 'loading',
              role: 'assistant',
              content: '',
              timestamp: new Date(),
              isLoading: true,
            }}
          />
        )}

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
