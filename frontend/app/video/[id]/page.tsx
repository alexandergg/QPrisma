'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'
import {
  Play,
  Pause,
  Film,
  ArrowLeft,
  Sparkles,
  Send,
  MessageSquare,
  Layers,
  ChevronRight,
  BookOpen,
  Mic,
  Eye,
  RotateCcw,
  Volume2,
  VolumeX,
  Maximize,
  SkipBack,
  SkipForward,
  Tag,
} from 'lucide-react'
import { apiClient } from '@/lib/api'

// ============================================================================
// Types
// ============================================================================

interface Frame {
  id: string
  frame_number: number
  timestamp: number
  content: string
  score: number
  type?: 'visual' | 'audio' | 'entity'  // Source type from hybrid search
  transcript_text?: string
  visual_description?: string
  detected_objects?: string[]
}

interface Scene {
  scene_id: number
  start_time: number
  end_time: number
  duration?: number
  title?: string
  summary?: string
  detected_objects?: string[]
  transcript_segment?: string
}

interface Chapter {
  chapter_id: number
  title: string
  start_time: number
  end_time: number
  duration?: number
  scene_ids?: number[]
  scene_count?: number
}

interface VideoStructure {
  scenes?: Scene[]
  chapters?: Chapter[]
  video_summary?: string
  video_title?: string
  key_topics?: string[]
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  frames?: Frame[]
  isLoading?: boolean
}

interface VideoMetadata {
  id: string
  blob_url: string
  file_name: string
  original_filename?: string
  duration?: number
  processing_result?: {
    frames_analyzed: number
  }
  audio_data?: {
    transcription?: {
      text: string
      segments: Array<{
        id: number
        start: number
        end: number
        text: string
      }>
    }
  }
}

// ============================================================================
// Fetcher
// ============================================================================

const fetcher = (url: string) => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null
  return fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  }).then((res) => {
    if (!res.ok) throw new Error('Video no encontrado')
    return res.json()
  })
}

// ============================================================================
// Utility Functions
// ============================================================================

function formatTime(seconds: number): string {
  if (!seconds || isNaN(seconds)) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function generateId(): string {
  return Math.random().toString(36).substring(2, 9)
}

// ============================================================================
// Component: SceneTimeline
// ============================================================================

function SceneTimeline({
  scenes,
  duration,
  currentTime,
  onSeek,
}: {
  scenes: Scene[]
  duration: number
  currentTime: number
  onSeek: (time: number) => void
}) {
  if (!scenes.length || !duration) return null

  return (
    <div className="relative h-2 bg-gray-200 rounded-full overflow-hidden group cursor-pointer">
      {/* Scene segments */}
      {scenes.map((scene, idx) => {
        const left = (scene.start_time / duration) * 100
        const width = ((scene.end_time - scene.start_time) / duration) * 100
        const isActive = currentTime >= scene.start_time && currentTime < scene.end_time
        const colors = [
          'bg-indigo-400',
          'bg-purple-400',
          'bg-blue-400',
          'bg-cyan-400',
          'bg-teal-400',
        ]

        return (
          <div
            key={scene.scene_id}
            className={`absolute top-0 h-full transition-all ${colors[idx % colors.length]} ${
              isActive ? 'opacity-100 ring-2 ring-white ring-inset' : 'opacity-70 hover:opacity-100'
            }`}
            style={{ left: `${left}%`, width: `${Math.max(width, 0.5)}%` }}
            onClick={() => onSeek(scene.start_time)}
            title={scene.title || `Scene ${scene.scene_id + 1}`}
          />
        )
      })}

      {/* Playhead */}
      <div
        className="absolute top-0 h-full w-0.5 bg-white shadow-lg z-10 pointer-events-none"
        style={{ left: `${(currentTime / duration) * 100}%` }}
      />
    </div>
  )
}

// ============================================================================
// Component: ChapterList
// ============================================================================

function ChapterList({
  structure,
  currentTime,
  onSeek,
  onReprocess,
  isReprocessing,
}: {
  structure: VideoStructure | null
  currentTime: number
  onSeek: (time: number) => void
  onReprocess?: () => void
  isReprocessing?: boolean
}) {
  const [expandedChapter, setExpandedChapter] = useState<number | null>(0)

  if (!structure) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-6">
        <Layers className="w-10 h-10 text-gray-300 mb-3" />
        <p className="text-gray-500 font-medium">No chapters available</p>
        <p className="text-gray-400 text-sm mt-1 mb-4">
          Process the video to generate chapter structure
        </p>
        {onReprocess && (
          <button
            onClick={onReprocess}
            disabled={isReprocessing}
            className="px-4 py-2 bg-indigo-500 hover:bg-indigo-600 disabled:bg-indigo-300 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
          >
            {isReprocessing ? (
              <>
                <RotateCcw className="w-4 h-4 animate-spin" />
                Processing...
              </>
            ) : (
              <>
                <RotateCcw className="w-4 h-4" />
                Generate Chapters
              </>
            )}
          </button>
        )}
      </div>
    )
  }

  const { scenes = [], chapters = [] } = structure

  // Find current scene
  const currentScene = scenes.find(
    (s) => currentTime >= s.start_time && currentTime < s.end_time
  )

  // If no chapters, show scenes directly
  if (chapters.length === 0 && scenes.length > 0) {
    return (
      <div className="space-y-1 p-3">
        {scenes.map((scene) => {
          const isActive = currentScene?.scene_id === scene.scene_id

          return (
            <button
              key={scene.scene_id}
              onClick={() => onSeek(scene.start_time)}
              className={`w-full text-left p-3 rounded-lg transition-all flex items-center gap-3 ${
                isActive
                  ? 'bg-indigo-50 border-l-4 border-indigo-500'
                  : 'hover:bg-gray-50'
              }`}
            >
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                  isActive ? 'bg-indigo-500 text-white' : 'bg-gray-100 text-gray-500'
                }`}
              >
                <Play className="w-3 h-3 fill-current" />
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm truncate ${isActive ? 'font-semibold text-indigo-700' : 'text-gray-700'}`}>
                  {scene.title || `Scene ${scene.scene_id + 1}`}
                </p>
                <p className="text-xs text-gray-400">{formatTime(scene.start_time)}</p>
              </div>
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <div className="space-y-2 p-3">
      {chapters.map((chapter) => {
        const isExpanded = expandedChapter === chapter.chapter_id
        const chapterScenes = scenes.filter((s) => chapter.scene_ids?.includes(s.scene_id))
        const isActive = chapterScenes.some((s) => currentScene?.scene_id === s.scene_id)

        return (
          <div key={chapter.chapter_id} className="rounded-lg overflow-hidden bg-gray-50">
            <button
              onClick={() => setExpandedChapter(isExpanded ? null : chapter.chapter_id)}
              className={`w-full text-left p-3 flex items-center gap-3 transition-all ${
                isActive ? 'bg-indigo-50' : 'hover:bg-gray-100'
              }`}
            >
              <div className={`transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                <ChevronRight className="w-4 h-4 text-gray-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className={`font-medium truncate ${isActive ? 'text-indigo-700' : 'text-gray-900'}`}>
                  {chapter.title}
                </p>
                <p className="text-xs text-gray-400">
                  {formatTime(chapter.start_time)} · {chapterScenes.length} scenes
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onSeek(chapter.start_time)
                }}
                className="p-1.5 rounded-full bg-white shadow hover:bg-indigo-50 transition-colors"
              >
                <Play className="w-3 h-3 text-indigo-600 fill-indigo-600" />
              </button>
            </button>

            {isExpanded && chapterScenes.length > 0 && (
              <div className="bg-white border-t border-gray-100 divide-y divide-gray-50">
                {chapterScenes.map((scene) => {
                  const isSceneActive = currentScene?.scene_id === scene.scene_id

                  return (
                    <button
                      key={scene.scene_id}
                      onClick={() => onSeek(scene.start_time)}
                      className={`w-full text-left p-3 pl-10 flex items-center gap-2 transition-all ${
                        isSceneActive ? 'bg-indigo-50' : 'hover:bg-gray-50'
                      }`}
                    >
                      <Play className={`w-3 h-3 ${isSceneActive ? 'text-indigo-600 fill-indigo-600' : 'text-gray-400'}`} />
                      <span className={`text-sm truncate ${isSceneActive ? 'text-indigo-700 font-medium' : 'text-gray-600'}`}>
                        {scene.title || `Scene ${scene.scene_id + 1}`}
                      </span>
                      <span className="text-xs text-gray-400 ml-auto">{formatTime(scene.start_time)}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ============================================================================
// Component: ChatInterface
// ============================================================================

function ChatInterface({
  videoId,
  onSeek,
}: {
  videoId: string
  onSeek: (time: number) => void
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Build chat history for context
  const getChatHistory = () => {
    return messages
      .filter(m => !m.isLoading)
      .map(m => ({ role: m.role, content: m.content }))
  }

  const handleSend = async () => {
    if (!input.trim() || isSearching) return

    const userMessage: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    }

    const loadingMessage: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isLoading: true,
    }

    setMessages((prev) => [...prev, userMessage, loadingMessage])
    const query = input.trim()
    setInput('')
    setIsSearching(true)

    try {
      // Use conversational chat endpoint with RAG
      const chatResponse = await apiClient.chatWithVideo(
        query,
        videoId,
        getChatHistory()
      )

      // Also get search results for sources
      const searchData = await apiClient.enhancedSearch(query, {
        mediaId: videoId,
        topK: 5,
        useReranking: true,
        useQueryExpansion: true,
      })

      const frames: Frame[] = searchData.results || []

      setMessages((prev) =>
        prev.map((msg) =>
          msg.isLoading
            ? {
                ...msg,
                content: chatResponse.response || "I analyzed the video but couldn't generate a response.",
                frames,
                isLoading: false,
              }
            : msg
        )
      )
    } catch {
      // Fallback to search-only if chat fails
      try {
        const searchData = await apiClient.enhancedSearch(query, {
          mediaId: videoId,
          topK: 5,
          useReranking: true,
          useQueryExpansion: true,
        })

        const frames: Frame[] = searchData.results || []
        const responseContent = frames.length > 0
          ? `I found ${frames.length} relevant moment${frames.length > 1 ? 's' : ''} in the video:`
          : "I couldn't find specific moments matching your query."

        setMessages((prev) =>
          prev.map((msg) =>
            msg.isLoading
              ? { ...msg, content: responseContent, frames, isLoading: false }
              : msg
          )
        )
      } catch {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.isLoading
              ? { ...msg, content: 'Sorry, there was an error. Please try again.', isLoading: false }
              : msg
          )
        )
      }
    } finally {
      setIsSearching(false)
    }
  }

  const handleClear = () => {
    setMessages([])
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-indigo-500" />
          <span className="font-semibold text-gray-900">Ask about this video</span>
        </div>
        {messages.length > 0 && (
          <button
            onClick={handleClear}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
            title="Clear chat"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-100 to-purple-100 flex items-center justify-center mb-4">
              <Sparkles className="w-7 h-7 text-indigo-500" />
            </div>
            <p className="text-gray-700 font-medium mb-1">AI Video Search</p>
            <p className="text-gray-400 text-sm max-w-[200px]">
              Ask questions about the video content in natural language
            </p>
            <div className="mt-6 space-y-2">
              <p className="text-xs text-gray-400">Try asking:</p>
              {['What happens at the beginning?', 'Show me action scenes', 'Find mentions of...'].map(
                (suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => setInput(suggestion)}
                    className="block w-full text-left px-3 py-2 text-sm text-gray-600 bg-gray-50 hover:bg-indigo-50 hover:text-indigo-700 rounded-lg transition-colors"
                  >
                    &quot;{suggestion}&quot;
                  </button>
                )
              )}
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                  message.role === 'user'
                    ? 'bg-indigo-500 text-white'
                    : 'bg-gray-100 text-gray-800'
                }`}
              >
                {message.isLoading ? (
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
                  </div>
                ) : (
                  <>
                    <p className="text-sm whitespace-pre-wrap">{message.content}</p>

                    {/* Sources from video - Enhanced with type indicators */}
                    {message.frames && message.frames.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-gray-200">
                        <p className="text-xs font-semibold text-gray-500 mb-2 flex items-center gap-1">
                          <Film className="w-3 h-3" />
                          Sources ({message.frames.length})
                        </p>
                        <div className="space-y-1.5">
                          {message.frames.slice(0, 5).map((frame, idx) => {
                            // Determine source type styling
                            const sourceType = frame.type || 'visual'
                            const typeConfig = {
                              visual: {
                                icon: Eye,
                                label: 'Visual',
                                bgColor: 'bg-blue-100',
                                textColor: 'text-blue-700',
                                borderHover: 'hover:border-blue-300',
                                bgHover: 'hover:bg-blue-50',
                              },
                              audio: {
                                icon: Mic,
                                label: 'Transcript',
                                bgColor: 'bg-green-100',
                                textColor: 'text-green-700',
                                borderHover: 'hover:border-green-300',
                                bgHover: 'hover:bg-green-50',
                              },
                              entity: {
                                icon: Tag,
                                label: 'Entity',
                                bgColor: 'bg-purple-100',
                                textColor: 'text-purple-700',
                                borderHover: 'hover:border-purple-300',
                                bgHover: 'hover:bg-purple-50',
                              },
                            }
                            const config = typeConfig[sourceType] || typeConfig.visual
                            const TypeIcon = config.icon

                            return (
                              <button
                                key={idx}
                                onClick={() => onSeek(frame.timestamp)}
                                className={`w-full text-left p-2.5 bg-white rounded-lg border border-gray-200 ${config.borderHover} ${config.bgHover} transition-all group flex items-start gap-2`}
                              >
                                {/* Type badge */}
                                <span className={`inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded ${config.bgColor} ${config.textColor} flex-shrink-0`}>
                                  <TypeIcon className="w-3 h-3" />
                                  {config.label}
                                </span>
                                {/* Timestamp */}
                                <span className="text-xs font-mono font-bold text-indigo-600 bg-indigo-100 px-1.5 py-0.5 rounded flex-shrink-0">
                                  {formatTime(frame.timestamp)}
                                </span>
                                {/* Content */}
                                <div className="flex-1 min-w-0">
                                  <p className="text-xs text-gray-700 line-clamp-2">{frame.content}</p>
                                  {frame.score > 0 && (
                                    <p className="text-[10px] text-gray-400 mt-0.5">
                                      Relevance: {(frame.score * 100).toFixed(0)}%
                                    </p>
                                  )}
                                </div>
                                {/* Play button */}
                                <Play className="w-3.5 h-3.5 text-gray-400 group-hover:text-indigo-500 flex-shrink-0 mt-0.5" />
                              </button>
                            )
                          })}
                          {message.frames.length > 5 && (
                            <p className="text-xs text-gray-400 text-center py-1">
                              +{message.frames.length - 5} more sources
                            </p>
                          )}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-gray-100">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Ask about the video..."
            className="flex-1 h-11 px-4 bg-gray-50 border border-gray-200 rounded-xl focus:border-indigo-500 focus:bg-white focus:outline-none transition-all text-sm text-gray-900 placeholder:text-gray-400"
            disabled={isSearching}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isSearching}
            className="h-11 w-11 flex items-center justify-center bg-indigo-500 hover:bg-indigo-600 disabled:bg-gray-200 disabled:cursor-not-allowed text-white rounded-xl transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// Main Component
// ============================================================================

export default function VideoDetailPage() {
  const params = useParams()
  const router = useRouter()
  const videoId = params.id as string

  // Data fetching
  const { data: metadata, error: swrError, isLoading } = useSWR<VideoMetadata>(
    videoId ? `http://localhost:8000/media/${videoId}` : null,
    fetcher,
    { revalidateOnFocus: false }
  )

  // State
  const [videoStructure, setVideoStructure] = useState<VideoStructure | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [activePanel, setActivePanel] = useState<'chapters' | 'chat' | 'transcript'>('chat')
  const [isReprocessing, setIsReprocessing] = useState(false)

  const videoRef = useRef<HTMLVideoElement>(null)

  // Fetch video structure
  useEffect(() => {
    if (videoId) {
      apiClient
        .getVideoStructure(videoId)
        .then((response) => {
          if (response?.structure) {
            setVideoStructure(response.structure)
          }
        })
        .catch(() => {
          // Silently fail - structure may not be available
        })
    }
  }, [videoId])

  // Reprocess video to generate chapters/scenes
  const handleReprocess = useCallback(async () => {
    if (!videoId || isReprocessing) return
    
    setIsReprocessing(true)
    try {
      await apiClient.reprocessWithOptimizedPipeline(videoId, {
        useSceneDetection: true,
        useHierarchicalSummary: true,
      })
      
      // Poll for completion (simple approach - check every 5 seconds)
      const pollInterval = setInterval(async () => {
        try {
          const response = await apiClient.getVideoStructure(videoId)
          if (response?.structure) {
            setVideoStructure(response.structure)
            setIsReprocessing(false)
            clearInterval(pollInterval)
          }
        } catch {
          // Keep polling
        }
      }, 5000)
      
      // Stop polling after 5 minutes
      setTimeout(() => {
        clearInterval(pollInterval)
        setIsReprocessing(false)
      }, 5 * 60 * 1000)
      
    } catch (error) {
      console.error('Reprocess failed:', error)
      setIsReprocessing(false)
    }
  }, [videoId, isReprocessing])

  // Video controls
  const handleSeek = useCallback((time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time
      videoRef.current.play()
      setIsPlaying(true)
    }
  }, [])

  const togglePlay = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause()
      } else {
        videoRef.current.play()
      }
      setIsPlaying(!isPlaying)
    }
  }

  const toggleMute = () => {
    if (videoRef.current) {
      videoRef.current.muted = !isMuted
      setIsMuted(!isMuted)
    }
  }

  const skip = (seconds: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime += seconds
    }
  }

  // Error state
  if (swrError) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center p-8">
          <Film className="w-12 h-12 text-gray-300 mx-auto mb-4" />
          <h1 className="text-xl font-bold text-gray-900 mb-2">Video Not Found</h1>
          <p className="text-gray-500 mb-6">{swrError.message}</p>
          <button
            onClick={() => router.push('/')}
            className="px-6 py-2 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 transition-colors"
          >
            Back to Home
          </button>
        </div>
      </div>
    )
  }

  // Loading state
  if (isLoading || !metadata) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-gray-200 border-t-indigo-500 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-500">Loading video...</p>
        </div>
      </div>
    )
  }

  const duration = metadata.duration || 0
  const scenes = videoStructure?.scenes || []

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-[1920px] mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push('/')}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <ArrowLeft className="w-5 h-5 text-gray-600" />
            </button>
            <div className="h-5 w-px bg-gray-200" />
            <div>
              <h1 className="text-sm font-semibold text-gray-900 truncate max-w-[300px]">
                {metadata.original_filename || metadata.file_name}
              </h1>
              <p className="text-xs text-gray-500">
                {metadata.processing_result?.frames_analyzed || 0} frames analyzed
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="px-2 py-1 bg-green-100 text-green-700 rounded-full text-xs font-medium">
              Ready
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-[1920px] mx-auto p-4">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 h-[calc(100vh-120px)]">
          {/* Left Panel: Chapters */}
          <div className="lg:col-span-3 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-indigo-500" />
              <span className="font-semibold text-gray-900">Chapters</span>
              {videoStructure && (
                <span className="ml-auto text-xs text-gray-400">
                  {videoStructure.chapters?.length || 0} chapters
                </span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto">
              <ChapterList 
                structure={videoStructure} 
                currentTime={currentTime} 
                onSeek={handleSeek}
                onReprocess={handleReprocess}
                isReprocessing={isReprocessing}
              />
            </div>
          </div>

          {/* Center: Video Player */}
          <div className="lg:col-span-6 flex flex-col gap-4">
            {/* Video Container */}
            <div className="bg-black rounded-xl overflow-hidden shadow-lg">
              <div className="relative aspect-video">
                <video
                  ref={videoRef}
                  src={metadata.blob_url}
                  className="w-full h-full object-contain"
                  onTimeUpdate={() => {
                    if (videoRef.current) {
                      setCurrentTime(videoRef.current.currentTime)
                    }
                  }}
                  onPlay={() => setIsPlaying(true)}
                  onPause={() => setIsPlaying(false)}
                  onClick={togglePlay}
                />

                {/* Play/Pause overlay */}
                {!isPlaying && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/20">
                    <button
                      onClick={togglePlay}
                      className="w-16 h-16 rounded-full bg-white/90 flex items-center justify-center shadow-lg hover:bg-white transition-colors"
                    >
                      <Play className="w-7 h-7 text-gray-900 fill-gray-900 ml-1" />
                    </button>
                  </div>
                )}
              </div>

              {/* Controls */}
              <div className="bg-gray-900 px-4 py-3">
                {/* Timeline with scenes */}
                <div className="mb-3">
                  <SceneTimeline
                    scenes={scenes}
                    duration={duration}
                    currentTime={currentTime}
                    onSeek={handleSeek}
                  />
                </div>

                {/* Control buttons */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <button onClick={() => skip(-10)} className="p-2 text-white/70 hover:text-white transition-colors">
                      <SkipBack className="w-4 h-4" />
                    </button>
                    <button onClick={togglePlay} className="p-2 text-white hover:text-indigo-400 transition-colors">
                      {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5 fill-current" />}
                    </button>
                    <button onClick={() => skip(10)} className="p-2 text-white/70 hover:text-white transition-colors">
                      <SkipForward className="w-4 h-4" />
                    </button>
                    <button onClick={toggleMute} className="p-2 text-white/70 hover:text-white transition-colors">
                      {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
                    </button>
                  </div>

                  <div className="text-sm text-white/70 font-mono">
                    {formatTime(currentTime)} / {formatTime(duration)}
                  </div>

                  <button className="p-2 text-white/70 hover:text-white transition-colors">
                    <Maximize className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>

            {/* Video Summary */}
            {videoStructure?.video_summary && (
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="w-4 h-4 text-indigo-500" />
                  <span className="font-semibold text-gray-900 text-sm">AI Summary</span>
                </div>
                <p className="text-gray-600 text-sm leading-relaxed">{videoStructure.video_summary}</p>
                {videoStructure.key_topics && videoStructure.key_topics.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-3">
                    {videoStructure.key_topics.map((topic, i) => (
                      <span key={i} className="px-2 py-1 bg-gray-100 text-gray-600 rounded-full text-xs">
                        {topic}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right Panel: Chat/Transcript */}
          <div className="lg:col-span-3 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
            {/* Panel tabs */}
            <div className="flex border-b border-gray-100">
              <button
                onClick={() => setActivePanel('chat')}
                className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
                  activePanel === 'chat'
                    ? 'text-indigo-600 border-b-2 border-indigo-500 bg-indigo-50/50'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <MessageSquare className="w-4 h-4 inline mr-1.5" />
                Chat
              </button>
              <button
                onClick={() => setActivePanel('transcript')}
                className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
                  activePanel === 'transcript'
                    ? 'text-indigo-600 border-b-2 border-indigo-500 bg-indigo-50/50'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Mic className="w-4 h-4 inline mr-1.5" />
                Transcript
              </button>
            </div>

            {/* Panel content */}
            <div className="flex-1 overflow-hidden">
              {activePanel === 'chat' && <ChatInterface videoId={videoId} onSeek={handleSeek} />}

              {activePanel === 'transcript' && (
                <div className="h-full overflow-y-auto p-4 space-y-3">
                  {metadata.audio_data?.transcription?.segments ? (
                    metadata.audio_data.transcription.segments.map((segment, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleSeek(segment.start)}
                        className="w-full text-left p-3 hover:bg-indigo-50 rounded-lg transition-colors group"
                      >
                        <span className="text-xs font-mono text-indigo-600 bg-indigo-100 px-1.5 py-0.5 rounded mr-2">
                          {formatTime(segment.start)}
                        </span>
                        <span className="text-sm text-gray-600 group-hover:text-gray-900">
                          {segment.text}
                        </span>
                      </button>
                    ))
                  ) : (
                    <div className="flex flex-col items-center justify-center h-full text-center">
                      <Mic className="w-10 h-10 text-gray-300 mb-3" />
                      <p className="text-gray-500 font-medium">No transcript available</p>
                      <p className="text-gray-400 text-sm mt-1">
                        This video doesn&apos;t have audio transcription
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
