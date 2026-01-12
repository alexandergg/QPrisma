'use client'

import { useState, useEffect, useRef } from 'react'
import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'
import { Search, Play, Film, Clock, ArrowLeft, Sparkles, TrendingUp, Mic, Eye, Box, Share2, MoreHorizontal, Zap, ChevronRight, Layers, Type, Target, Wand2, BookOpen, ToggleLeft, ToggleRight } from 'lucide-react'
import VideoOverlay from '@/components/VideoOverlay'
import ChapterNavigation from '@/components/ChapterNavigation'
import { apiClient } from '@/lib/api'

interface Frame {
  id: string
  frame_number: number
  timestamp: number
  content: string
  score: number
  transcript_text?: string
  visual_description?: string
  detected_objects?: string[]
}

interface VideoMetadata {
  id: string
  blob_url: string
  file_name: string
  duration?: number
  processing_result?: {
    frames_analyzed: number
  }
  objects_data?: {
    frames?: any[]
    objects?: any[]
  }
  audio_data?: {
    transcription?: {
      text: string
      segments: Array<{
        id: number
        seek: number
        start: number
        end: number
        text: string
        tokens: number[]
        temperature: number
        avg_logprob: number
        compression_ratio: number
        no_speech_prob: number
      }>
    }
  }
}

const fetcher = (url: string) => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  return fetch(url, {
    headers: token ? { 'Authorization': `Bearer ${token}` } : {},
  }).then((res) => {
    if (!res.ok) throw new Error('Video no encontrado')
    return res.json()
  })
}

export default function VideoSearchPage() {
  const params = useParams()
  const router = useRouter()
  const videoId = params.id as string

  // Use SWR for data fetching
  const { data: metadata, error: swrError, isLoading } = useSWR<VideoMetadata>(
    videoId ? `http://localhost:8000/media/${videoId}` : null,
    fetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 60000,
    }
  )

  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Frame[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searchPerformed, setSearchPerformed] = useState(false)
  const [activeTab, setActiveTab] = useState<'search' | 'transcript'>('search')

  // Video Overlay State
  const [currentTime, setCurrentTime] = useState(0)
  const [videoDimensions, setVideoDimensions] = useState({ width: 0, height: 0 })
  const [naturalDimensions, setNaturalDimensions] = useState({ width: 0, height: 0 })
  const [showOverlay, setShowOverlay] = useState(true)

  // Layer Toggles
  const [showDetections, setShowDetections] = useState(true)
  const [showPoints, setShowPoints] = useState(true)
  const [showCaptions, setShowCaptions] = useState(true)

  // Magic Tool State
  const [magicToolActive, setMagicToolActive] = useState(false)
  const [magicMasks, setMagicMasks] = useState<any[]>([])
  const [isSegmenting, setIsSegmenting] = useState(false)
  const [isGenerating3D, setIsGenerating3D] = useState(false)

  // New: Video Structure & Enhanced Search
  const [videoStructure, setVideoStructure] = useState<any>(null)
  const [useEnhancedSearch, setUseEnhancedSearch] = useState(true)
  const [showChapterNav, setShowChapterNav] = useState(true)

  const videoRef = useRef<HTMLVideoElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Handle 3D Generation
  const handleGenerate3D = async () => {
    if (magicMasks.length === 0 || !videoRef.current) return;

    setIsGenerating3D(true);
    try {
      const lastMask = magicMasks[magicMasks.length - 1];

      const token = localStorage.getItem('auth_token');
      const response = await fetch(`http://localhost:8000/media/${videoId}/magic-tool/3d`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {})
        },
        body: JSON.stringify({
          timestamp: videoRef.current.currentTime,
          mask_polygon: lastMask.polygon,
          bbox: lastMask.bbox
        })
      });

      if (!response.ok) {
        const err = await response.json();
        alert(`3D Generation Error: ${err.detail}`);
        throw new Error(err.detail);
      }

      const data = await response.json();
      alert("3D Model Generated! (Check backend logs/temp folder for now)");

    } catch (err) {
      console.error("3D Gen Error:", err);
    } finally {
      setIsGenerating3D(false);
    }
  };

  // Handle Magic Tool Click
  const handleVideoClick = async (e: React.MouseEvent<HTMLDivElement>) => {
    if (!magicToolActive || !videoRef.current || isSegmenting) return;

    const rect = videoRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    if (naturalDimensions.width === 0 || naturalDimensions.height === 0) return;

    const scaleX = naturalDimensions.width / rect.width;
    const scaleY = naturalDimensions.height / rect.height;

    const originalX = Math.round(x * scaleX);
    const originalY = Math.round(y * scaleY);

    setIsSegmenting(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`http://localhost:8000/media/${videoId}/magic-tool`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {})
        },
        body: JSON.stringify({
          timestamp: videoRef.current.currentTime,
          points: [[originalX, originalY]],
          labels: [1]
        })
      });

      if (!response.ok) throw new Error('Segmentation failed');

      const data = await response.json();
      if (data.masks) {
        setMagicMasks(prev => [...prev, ...data.masks]);
      }
    } catch (err) {
      console.error("Magic Tool Error:", err);
    } finally {
      setIsSegmenting(false);
    }
  };

  // Handle resize
  useEffect(() => {
    const updateDimensions = () => {
      if (videoRef.current) {
        setVideoDimensions({
          width: videoRef.current.clientWidth,
          height: videoRef.current.clientHeight
        })
      }
    }

    window.addEventListener('resize', updateDimensions)
    return () => window.removeEventListener('resize', updateDimensions)
  }, [])

  // Update error state from SWR
  useEffect(() => {
    if (swrError) {
      console.error('Error loading metadata:', swrError)
      setError(swrError.message || 'Error cargando video')
    }
  }, [swrError])

  // Fetch video structure (scenes, chapters)
  useEffect(() => {
    if (videoId) {
      apiClient.getVideoStructure(videoId)
        .then((response) => {
          // API returns { media_id, structure: {...}, processing_method, processed_at }
          // ChapterNavigation expects the structure object directly
          if (response && response.structure) {
            setVideoStructure(response.structure)
          }
        })
        .catch((err) => {
          console.log('No video structure available:', err.message)
        })
    }
  }, [videoId])

  // Search in video
  async function handleSearch() {
    if (!query.trim()) return

    setLoading(true)
    setError('')
    setSearchPerformed(true)

    try {
      let data;
      if (useEnhancedSearch) {
        // Use enhanced search with re-ranking and query expansion
        data = await apiClient.enhancedSearch(query, {
          mediaId: videoId,
          topK: 20,
          useReranking: true,
          useQueryExpansion: true,
          clusterByTime: true,
        });
        setResults(data.results || [])
      } else {
        // Use standard search
        const token = localStorage.getItem('auth_token');
        const res = await fetch(
          `http://localhost:8000/media/${videoId}/search?query=${encodeURIComponent(query)}&top=20`,
          {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
          }
        )

        if (!res.ok) throw new Error('Error en busqueda')

        data = await res.json()
        setResults(data.results || [])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error en busqueda')
    } finally {
      setLoading(false)
    }
  }

  // Jump to timestamp
  function jumpToTimestamp(timestamp: number) {
    if (videoRef.current) {
      videoRef.current.currentTime = timestamp
      videoRef.current.play()
    }
  }

  if (error && !metadata) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 flex items-center justify-center">
        <div className="text-center p-8 max-w-md">
          <div className="bg-gradient-to-br from-red-100 to-orange-100 rounded-3xl w-20 h-20 flex items-center justify-center mx-auto mb-6 shadow-xl shadow-red-200/50">
            <Film className="w-8 h-8 text-red-500" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Error Loading Video</h1>
          <p className="text-gray-500 mb-8">{error}</p>
          <button
            onClick={() => router.push('/')}
            className="px-8 py-3 bg-gradient-to-r from-indigo-500 to-purple-600 text-white rounded-xl hover:from-indigo-600 hover:to-purple-700 transition-all font-semibold shadow-lg shadow-indigo-500/30"
          >
            Back to Home
          </button>
        </div>
      </div>
    )
  }

  if (isLoading || !metadata) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 flex items-center justify-center">
        <div className="text-center">
          <div className="relative mb-6">
            <div className="w-16 h-16 border-4 border-gray-200 border-t-indigo-500 rounded-full animate-spin mx-auto"></div>
          </div>
          <p className="text-gray-500 font-medium">Loading video intelligence...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 font-sans selection:bg-indigo-100 selection:text-indigo-900">
      {/* Decorative Elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-gradient-to-br from-indigo-200/30 to-purple-200/30 rounded-full blur-3xl"></div>
        <div className="absolute bottom-0 -left-40 w-96 h-96 bg-gradient-to-br from-blue-200/20 to-cyan-200/20 rounded-full blur-3xl"></div>
      </div>

      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/70 backdrop-blur-xl border-b border-gray-200/50 shadow-sm">
        <div className="max-w-[1920px] mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push('/')}
              className="p-2 hover:bg-gray-100 rounded-xl transition-colors group"
              title="Back to Dashboard"
            >
              <ArrowLeft className="w-5 h-5 text-gray-600 group-hover:text-indigo-600 transition-colors" />
            </button>

            <div className="h-6 w-px bg-gray-200"></div>

            <div className="flex items-center gap-3">
              <div className="bg-gradient-to-br from-indigo-500 to-purple-600 w-8 h-8 rounded-lg flex items-center justify-center shadow-lg shadow-indigo-500/30">
                <Zap className="w-4 h-4 text-white" />
              </div>
              <div>
                <h1 className="text-sm font-bold text-gray-900 leading-none">
                  {metadata.file_name}
                </h1>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-gray-500">{metadata.processing_result?.frames_analyzed || 0} frames analyzed</span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button className="p-2 hover:bg-gray-100 rounded-xl transition-colors text-gray-500 hover:text-gray-700">
              <Share2 className="w-5 h-5" />
            </button>
            <button className="p-2 hover:bg-gray-100 rounded-xl transition-colors text-gray-500 hover:text-gray-700">
              <MoreHorizontal className="w-5 h-5" />
            </button>
            <div className="h-6 w-px bg-gray-200 mx-1"></div>
            <div className="flex items-center gap-2 px-3 py-1.5 bg-green-100 text-green-700 rounded-full">
              <div className="w-2 h-2 rounded-full bg-green-500"></div>
              <span className="text-xs font-semibold">Ready</span>
            </div>
          </div>
        </div>
      </header>

      <div className="relative max-w-[1920px] mx-auto px-6 py-6">
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">

          {/* Left Column: Video & Timeline (8 cols) */}
          <div className="xl:col-span-8 space-y-6">
            {/* Video Player Container */}
            <div className="bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 overflow-hidden">
              {/* Video Header */}
              <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-indigo-100 rounded-lg">
                    <Play className="w-4 h-4 text-indigo-600 fill-indigo-600" />
                  </div>
                  <h2 className="font-bold text-gray-900">Video Player</h2>
                </div>

                <div className="flex items-center gap-2">
                  {/* Layer Controls */}
                  <div className="flex items-center gap-1 bg-gray-100 p-1 rounded-lg mr-2">
                    <button
                      onClick={() => setShowDetections(!showDetections)}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${showDetections ? 'bg-white text-indigo-600 shadow' : 'text-gray-500 hover:text-gray-700'
                        }`}
                      title="Toggle Detections"
                    >
                      <Box className="w-3 h-3" /> Boxes
                    </button>
                    <button
                      onClick={() => setShowPoints(!showPoints)}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${showPoints ? 'bg-white text-indigo-600 shadow' : 'text-gray-500 hover:text-gray-700'
                        }`}
                      title="Toggle Points"
                    >
                      <Target className="w-3 h-3" /> Points
                    </button>
                    <button
                      onClick={() => setShowCaptions(!showCaptions)}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${showCaptions ? 'bg-white text-indigo-600 shadow' : 'text-gray-500 hover:text-gray-700'
                        }`}
                      title="Toggle Captions"
                    >
                      <Type className="w-3 h-3" /> Text
                    </button>
                  </div>

                  {/* Magic Tool Button */}
                  <button
                    onClick={() => {
                      setMagicToolActive(!magicToolActive);
                      if (!magicToolActive) {
                        videoRef.current?.pause();
                      }
                    }}
                    className={`px-4 py-2 rounded-xl text-xs font-semibold transition-all border flex items-center gap-2 ${magicToolActive
                        ? 'bg-gradient-to-r from-violet-500 to-purple-500 text-white border-transparent shadow-lg shadow-violet-500/30'
                        : 'bg-white text-gray-600 border-gray-200 hover:border-violet-300 hover:text-violet-600'
                      }`}
                  >
                    <Wand2 className={`w-4 h-4 ${isSegmenting ? 'animate-spin' : ''}`} />
                    {isSegmenting ? 'Segmenting...' : (magicToolActive ? 'Magic ON' : 'Magic Tool')}
                  </button>

                  {/* 3D Generation Button */}
                  {magicMasks.length > 0 && (
                    <button
                      onClick={handleGenerate3D}
                      disabled={isGenerating3D}
                      className="px-4 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 bg-gradient-to-r from-cyan-500 to-blue-500 text-white shadow-lg shadow-cyan-500/30 hover:shadow-xl disabled:opacity-50"
                    >
                      <Box className={`w-4 h-4 ${isGenerating3D ? 'animate-bounce' : ''}`} />
                      {isGenerating3D ? 'Generating...' : 'Make 3D'}
                    </button>
                  )}

                  <button
                    onClick={() => setShowOverlay(!showOverlay)}
                    className={`px-4 py-2 rounded-xl text-xs font-semibold transition-all border flex items-center gap-2 ${showOverlay
                        ? 'bg-indigo-500 text-white border-transparent shadow-lg shadow-indigo-500/30'
                        : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300 hover:text-indigo-600'
                      }`}
                  >
                    <Layers className="w-4 h-4" />
                    Overlay
                  </button>
                </div>
              </div>

              {/* Video */}
              <div
                ref={containerRef}
                className={`relative w-full bg-gray-900 ${magicToolActive ? 'cursor-crosshair' : ''}`}
                onClick={handleVideoClick}
              >
                <video
                  ref={videoRef}
                  controls={!magicToolActive}
                  crossOrigin="anonymous"
                  className="w-full h-auto block"
                  src={metadata.blob_url}
                  onTimeUpdate={() => {
                    if (videoRef.current) {
                      setCurrentTime(videoRef.current.currentTime)
                    }
                  }}
                  onLoadedMetadata={() => {
                    if (videoRef.current) {
                      setNaturalDimensions({
                        width: videoRef.current.videoWidth,
                        height: videoRef.current.videoHeight
                      })
                      setVideoDimensions({
                        width: videoRef.current.clientWidth,
                        height: videoRef.current.clientHeight
                      })
                    }
                  }}
                >
                  Your browser does not support HTML5 video
                </video>

                {showOverlay && (
                  <VideoOverlay
                    frames={metadata.objects_data?.frames || []}
                    currentTime={currentTime}
                    width={videoDimensions.width}
                    height={videoDimensions.height}
                    showDetections={showDetections}
                    showPoints={showPoints}
                    showCaptions={showCaptions}
                    magicMasks={magicMasks}
                  />
                )}
              </div>
            </div>

            {/* Timeline */}
            {results.length > 0 && (
              <div className="bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 p-6">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-indigo-100 rounded-lg">
                      <TrendingUp className="w-4 h-4 text-indigo-600" />
                    </div>
                    <div>
                      <h3 className="font-bold text-gray-900">Timeline Analysis</h3>
                      <p className="text-xs text-gray-500">{results.length} matches found</p>
                    </div>
                  </div>
                </div>

                <div className="relative h-20 flex items-center px-4">
                  {/* The Line */}
                  <div className="absolute left-4 right-4 h-1 bg-gradient-to-r from-gray-200 via-indigo-200 to-gray-200 rounded-full"></div>

                  {/* The Dots */}
                  {results.map((result, idx) => {
                    const position = metadata.duration
                      ? (result.timestamp / metadata.duration) * 100
                      : 0

                    const isHighConfidence = result.score > 0.8

                    return (
                      <button
                        key={idx}
                        onClick={() => jumpToTimestamp(result.timestamp)}
                        className="absolute group focus:outline-none transition-all duration-300"
                        style={{ left: `${Math.max(2, Math.min(98, position))}%` }}
                      >
                        {/* Dot */}
                        <div className={`
                          relative z-10 rounded-full transition-all duration-300 shadow-lg
                          ${isHighConfidence
                            ? 'w-4 h-4 bg-gradient-to-r from-indigo-500 to-purple-500 ring-4 ring-white'
                            : 'w-3 h-3 bg-gray-400 hover:bg-indigo-400'
                          }
                          group-hover:scale-150
                        `}></div>

                        {/* Tooltip */}
                        <div className="absolute bottom-10 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-all duration-300 pointer-events-none min-w-[200px] z-20">
                          <div className="bg-gray-900 text-white p-3 rounded-xl shadow-2xl text-center">
                            <div className="text-xs font-bold text-indigo-400 mb-1">
                              {Math.floor(result.timestamp)}s
                            </div>
                            <div className="text-sm font-medium line-clamp-2">
                              {result.content}
                            </div>
                          </div>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Search & Results (4 cols) */}
          <div className="xl:col-span-4 flex flex-col h-[calc(100vh-120px)] sticky top-20">

            {/* Tabs */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-1 bg-gray-100 p-1 rounded-xl">
                <button
                  onClick={() => setActiveTab('search')}
                  className={`px-5 py-2 rounded-lg text-sm font-semibold transition-all ${activeTab === 'search'
                      ? 'bg-white text-indigo-600 shadow'
                      : 'text-gray-500 hover:text-gray-700'
                    }`}
                >
                  Search
                </button>
                <button
                  onClick={() => setActiveTab('transcript')}
                  className={`px-5 py-2 rounded-lg text-sm font-semibold transition-all ${activeTab === 'transcript'
                      ? 'bg-white text-indigo-600 shadow'
                      : 'text-gray-500 hover:text-gray-700'
                    }`}
                >
                  Transcript
                </button>
              </div>

              {/* Chapter Nav Toggle */}
              {videoStructure && (
                <button
                  onClick={() => setShowChapterNav(!showChapterNav)}
                  className={`px-3 py-2 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                    showChapterNav
                      ? 'bg-indigo-100 text-indigo-700'
                      : 'bg-gray-100 text-gray-500 hover:text-gray-700'
                  }`}
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  Chapters
                </button>
              )}
            </div>

            {activeTab === 'search' ? (
              <>
                {/* Enhanced Search Toggle */}
                <div className="flex items-center justify-between mb-3 px-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-gray-500">Search Mode:</span>
                    <button
                      onClick={() => setUseEnhancedSearch(!useEnhancedSearch)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                        useEnhancedSearch
                          ? 'bg-gradient-to-r from-indigo-500 to-purple-500 text-white shadow-lg shadow-indigo-500/30'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      <Sparkles className="w-3 h-3" />
                      {useEnhancedSearch ? 'AI Enhanced' : 'Standard'}
                    </button>
                  </div>
                  {useEnhancedSearch && (
                    <span className="text-[10px] text-indigo-500 font-medium">Re-ranking + Query Expansion</span>
                  )}
                </div>

                {/* Search Input */}
                <div className="mb-4">
                  <div className="relative group">
                    <input
                      type="text"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                      placeholder="Search objects, actions, text..."
                      className="w-full h-14 pl-12 pr-24 bg-white border-2 border-gray-200 rounded-xl focus:border-indigo-500 focus:outline-none transition-all text-gray-900 placeholder-gray-400 shadow-lg shadow-gray-200/50"
                      disabled={loading}
                    />
                    <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-indigo-500 transition-colors" />

                    {query && (
                      <button
                        onClick={handleSearch}
                        disabled={loading}
                        className="absolute right-2 top-2 bottom-2 px-5 bg-gradient-to-r from-indigo-500 to-purple-500 hover:from-indigo-600 hover:to-purple-600 text-white rounded-lg font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 shadow-lg shadow-indigo-500/30"
                      >
                        {loading ? (
                          <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                        ) : (
                          'Search'
                        )}
                      </button>
                    )}
                  </div>
                </div>

                {/* Chapter Navigation (when available and toggled) */}
                {videoStructure && showChapterNav && (
                  <div className="mb-4 max-h-64 overflow-hidden">
                    <ChapterNavigation
                      structure={videoStructure}
                      currentTime={currentTime}
                      onSeek={jumpToTimestamp}
                      duration={metadata?.duration || 0}
                    />
                  </div>
                )}

                {/* Results List */}
                <div className="flex-1 bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 overflow-hidden flex flex-col">
                  <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                    <h3 className="font-bold text-gray-900">Results</h3>
                    {results.length > 0 && (
                      <span className="bg-indigo-100 text-indigo-700 px-3 py-1 rounded-full text-xs font-bold">
                        {results.length} found
                      </span>
                    )}
                  </div>

                  <div className="flex-1 overflow-y-auto p-4 space-y-2">
                    {!searchPerformed && !loading && (
                      <div className="h-full flex flex-col items-center justify-center text-center p-8">
                        <div className="bg-gradient-to-br from-indigo-100 to-purple-100 rounded-2xl w-16 h-16 flex items-center justify-center mb-4 shadow-lg shadow-indigo-200/50">
                          <Sparkles className="w-7 h-7 text-indigo-500" />
                        </div>
                        <p className="text-gray-700 font-semibold mb-1">AI-Powered Search</p>
                        <p className="text-gray-400 text-sm max-w-[200px]">
                          Describe what you're looking for in natural language
                        </p>
                      </div>
                    )}

                    {results.map((result, idx) => (
                      <button
                        key={idx}
                        onClick={() => jumpToTimestamp(result.timestamp)}
                        className="w-full text-left p-4 bg-gray-50 hover:bg-indigo-50 border border-gray-100 hover:border-indigo-200 rounded-xl transition-all group relative overflow-hidden"
                      >
                        {/* Left accent bar */}
                        <div
                          className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-indigo-500 to-purple-500 rounded-l-xl"
                          style={{ opacity: result.score }}
                        ></div>

                        <div className="flex items-start justify-between mb-2 pl-3">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs text-indigo-600 font-bold bg-indigo-100 px-2 py-0.5 rounded">
                              {new Date(result.timestamp * 1000).toISOString().substr(14, 5)}
                            </span>
                            <span className="text-gray-400 text-xs">Frame {result.frame_number}</span>
                          </div>
                          <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                            <Play className="w-4 h-4 text-indigo-600 fill-indigo-600" />
                          </div>
                        </div>

                        <p className="text-gray-600 text-sm leading-relaxed pl-3 line-clamp-2 group-hover:text-gray-900 transition-colors">
                          {result.content}
                        </p>

                        {result.detected_objects && result.detected_objects.length > 0 && (
                          <div className="flex gap-1.5 mt-3 pl-3 flex-wrap">
                            {result.detected_objects.slice(0, 3).map((obj, i) => (
                              <span key={i} className="text-[10px] uppercase tracking-wider font-bold text-gray-500 bg-white px-2 py-1 rounded-md border border-gray-200">
                                {obj}
                              </span>
                            ))}
                          </div>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex-1 bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 overflow-hidden flex flex-col">
                <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                  <h3 className="font-bold text-gray-900">Full Transcript</h3>
                  <div className="flex items-center gap-2">
                    <Mic className="w-4 h-4 text-indigo-500" />
                    <span className="text-xs font-medium text-gray-500">
                      {metadata.audio_data?.transcription?.segments.length || 0} segments
                    </span>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {metadata.audio_data?.transcription?.segments.map((segment, idx) => (
                    <button
                      key={idx}
                      onClick={() => jumpToTimestamp(segment.start)}
                      className="w-full text-left p-4 hover:bg-indigo-50 rounded-xl transition-colors group"
                    >
                      <div className="flex items-center gap-2 mb-2">
                        <span className="font-mono text-xs text-indigo-600 font-bold bg-indigo-100 px-2 py-0.5 rounded">
                          {new Date(segment.start * 1000).toISOString().substr(14, 5)}
                        </span>
                        <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                          <Play className="w-3 h-3 text-indigo-500 fill-indigo-500" />
                        </div>
                      </div>
                      <p className="text-gray-600 text-sm leading-relaxed group-hover:text-gray-900 transition-colors">
                        {segment.text}
                      </p>
                    </button>
                  ))}

                  {!metadata.audio_data?.transcription && (
                    <div className="h-full flex flex-col items-center justify-center text-center p-8">
                      <div className="bg-gradient-to-br from-gray-100 to-gray-200 rounded-2xl w-16 h-16 flex items-center justify-center mb-4">
                        <Mic className="w-7 h-7 text-gray-400" />
                      </div>
                      <p className="text-gray-700 font-semibold mb-1">No Transcript Available</p>
                      <p className="text-gray-400 text-sm">
                        This video doesn't have audio transcription data.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
