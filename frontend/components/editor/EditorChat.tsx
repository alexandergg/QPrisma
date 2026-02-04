'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Send,
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
import { apiClient, Clip } from '@/lib/api';

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

interface EditorChatProps {
  projectId: string;
  onClipsUpdated?: (clips: Clip[]) => void;
  onTimestampClick?: (timestamp: number) => void;
}

// Quick action suggestions
const QUICK_ACTIONS = [
  { icon: Sparkles, label: 'Generate viral clips', message: 'Generate 5 viral clips from this video' },
  { icon: Search, label: 'Find highlights', message: 'Find the most engaging moments' },
  { icon: Subtitles, label: 'Add subtitles', message: 'Add subtitles to all clips with hormozi style' },
  { icon: Download, label: 'Export all', message: 'Export all clips for TikTok' },
];

/**
 * Chat component specialized for the video editor
 */
export default function EditorChat({
  projectId,
  onClipsUpdated,
  onTimestampClick,
}: EditorChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [activeTools, setActiveTools] = useState<ToolStatus[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const generateId = () => Math.random().toString(36).substring(2, 9);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  };

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);
    setStreamingContent('');
    setActiveTools([]);

    // Reset textarea height
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }

    try {
      // Build chat history for context
      const chatHistory = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      let finalResponse = '';
      let toolCallsMade = 0;

      // Use the editor-specific streaming endpoint
      for await (const event of apiClient.chatWithEditorAgentStream(
        userMessage.content,
        projectId,
        chatHistory,
        sessionId
      )) {
        switch (event.event) {
          case 'session':
            setSessionId(event.data.session_id);
            break;

          case 'thinking':
            // Could show a thinking indicator
            break;

          case 'tool_start':
            setActiveTools((prev) => [
              ...prev,
              { name: event.data.tool || 'unknown', status: 'running' },
            ]);
            break;

          case 'tool_end':
            setActiveTools((prev) =>
              prev.map((t) =>
                t.name === event.data.tool
                  ? { ...t, status: event.data.success ? 'success' : 'error' }
                  : t
              )
            );
            break;

          case 'token':
            if (event.data.token) {
              setStreamingContent((prev) => prev + event.data.token);
            }
            break;

          case 'clips_updated':
            // Notify parent that clips have been updated
            if (event.data.clips) {
              onClipsUpdated?.(event.data.clips);
            }
            break;

          case 'done':
            finalResponse = event.data.response || '';
            toolCallsMade = event.data.tool_calls_made || 0;
            break;

          case 'error':
            throw new Error(event.data.error || 'Unknown error');
        }
      }

      // Create final assistant message
      const assistantMessage: ChatMessage = {
        id: generateId(),
        role: 'assistant',
        content: finalResponse,
        timestamp: new Date(),
        toolCalls: toolCallsMade > 0 ? toolCallsMade : undefined,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setStreamingContent('');
      setActiveTools([]);
    } catch (error) {
      console.error('Chat error:', error);

      const errorMessage: ChatMessage = {
        id: generateId(),
        role: 'assistant',
        content:
          error instanceof Error
            ? `Sorry, I encountered an error: ${error.message}`
            : 'Sorry, I encountered an error processing your request. Please try again.',
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, errorMessage]);
      setStreamingContent('');
      setActiveTools([]);
    } finally {
      setIsLoading(false);
    }
  }, [inputValue, isLoading, messages, projectId, sessionId, onClipsUpdated]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleQuickAction = (message: string) => {
    setInputValue(message);
    inputRef.current?.focus();
  };

  // Parse timestamps in message content and make them clickable
  const renderMessageContent = (content: string) => {
    // Separate suggestions if present
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

    // Match timestamps like [12:34], 12:34, [1:23:45], etc.
    const timestampRegex = /\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?/g;
    const parts: (string | React.ReactNode)[] = [];
    let lastIndex = 0;
    let match;

    while ((match = timestampRegex.exec(displayContent)) !== null) {
      // Add text before the timestamp
      if (match.index > lastIndex) {
        parts.push(displayContent.slice(lastIndex, match.index));
      }

      // Parse timestamp to seconds
      const hours = match[3] ? parseInt(match[1]) : 0;
      const minutes = match[3] ? parseInt(match[2]) : parseInt(match[1]);
      const seconds = match[3] ? parseInt(match[3]) : parseInt(match[2]);
      const totalSeconds = hours * 3600 + minutes * 60 + seconds;

      // Add clickable timestamp
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

    // Add remaining text
    if (lastIndex < displayContent.length) {
      parts.push(displayContent.slice(lastIndex));
    }

    // Return content with suggestions appended
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
                  onClick={() => handleQuickAction(suggestion)}
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

  const hasMessages = messages.length > 0;

  return (
    <div className="flex flex-col h-full">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto">
        {!hasMessages ? (
          // Welcome state
          <div className="flex flex-col items-center justify-center h-full p-6 text-center">
            <div className="w-16 h-16 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center mb-4 shadow-lg">
              <Scissors className="w-8 h-8 text-white" />
            </div>
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              Chat-to-Edit
            </h2>
            <p className="text-gray-500 mb-6 max-w-md">
              Tell me what you want to do with your video. Search for moments,
              create clips, add subtitles, and export for any platform.
            </p>

            {/* Quick Actions */}
            <div className="grid grid-cols-2 gap-2 w-full max-w-md">
              {QUICK_ACTIONS.map((action, i) => (
                <button
                  key={i}
                  onClick={() => handleQuickAction(action.message)}
                  className="flex items-center gap-2 p-3 bg-white border border-gray-200 rounded-xl hover:border-indigo-300 hover:bg-indigo-50 transition-all text-left"
                >
                  <action.icon className="w-5 h-5 text-indigo-500 flex-shrink-0" />
                  <span className="text-sm text-gray-700">{action.label}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          // Messages list
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

            {/* Active Tools inside chat stream */}
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
                            <span className="font-medium">
                              {tool.name.replace(/_/g, ' ')}
                            </span>
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
        )}
      </div>

      {/* Input Area */}
      <div className="border-t border-gray-200 p-4 bg-white">
        <div className="flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={inputValue}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask me to search, create clips, add subtitles..."
              disabled={isLoading}
              rows={1}
              className="w-full px-4 py-3 bg-gray-100 border border-transparent rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ maxHeight: '120px' }}
            />
          </div>
          <button
            onClick={handleSend}
            disabled={!inputValue.trim() || isLoading}
            className="p-3 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
        <p className="mt-2 text-xs text-gray-400 text-center">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
