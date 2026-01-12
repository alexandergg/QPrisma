'use client';

import React, { useState, useEffect } from 'react';
import { Film, Upload, Video, Clock, Database, Search as SearchIcon, Play, Sparkles, Plus, FileVideo, Trash2, Grid, List, MoreVertical, LogOut, User, ChevronRight, Zap, BarChart3, Eye, Layers, Cpu } from 'lucide-react';
import VideoUpload from './VideoUpload';
import { apiClient } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { useRouter } from 'next/navigation';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Preset {
  name: string;
  description: string;
}

interface MediaItem {
  id: string;
  original_filename: string;
  media_type: string;
  file_size: number;
  uploaded_at: string;
  processed: boolean;
  processing_status: string;
  duration?: number;
  frames_analyzed?: number;
}

export default function VideoProcessingStudio() {
  const router = useRouter();
  const { user, logout } = useAuth();
  const [showUpload, setShowUpload] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<string>('balanced');
  const [maxFrames, setMaxFrames] = useState<number>(100);
  const [mediaList, setMediaList] = useState<MediaItem[]>([]);
  const [loadingMedia, setLoadingMedia] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [useOptimizedPipeline, setUseOptimizedPipeline] = useState(true);
  const [sceneDetectionEnabled, setSceneDetectionEnabled] = useState(true);
  const [hierarchicalSummaryEnabled, setHierarchicalSummaryEnabled] = useState(true);

  // Cargar presets y videos
  useEffect(() => {
    loadPresets();
    loadMediaList();
  }, []);

  const loadPresets = async () => {
    try {
      const response = await fetch(`${API_URL}/presets`);
      const data = await response.json();
      setPresets(data.presets || []);
    } catch (error) {
      console.error('Error loading presets:', error);
      setPresets([]);
    }
  };

  const loadMediaList = async () => {
    try {
      setLoadingMedia(true);
      const response = await apiClient.getMedia();
      setMediaList(response.media || []);
    } catch (error) {
      console.error('Error loading media list:', error);
      setMediaList([]);
    } finally {
      setLoadingMedia(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, mediaId: string) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this video? This action cannot be undone.')) {
      return;
    }

    try {
      await apiClient.deleteMedia(mediaId);
      setMediaList(mediaList.filter(item => item.id !== mediaId));
    } catch (error) {
      console.error('Error deleting media:', error);
      alert('Failed to delete video');
    }
  };

  const filteredMedia = mediaList.filter(item =>
    item.original_filename.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const processedCount = mediaList.filter(m => m.processed).length;
  const pendingCount = mediaList.filter(m => !m.processed).length;

  if (showUpload) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 font-sans">
        {/* Decorative Elements */}
        <div className="fixed inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl"></div>
          <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl"></div>
        </div>

        <div className="relative flex min-h-screen">
          {/* Sidebar */}
          <div className="w-72 bg-white/70 backdrop-blur-xl border-r border-gray-200/50 flex flex-col sticky top-0 h-screen shadow-xl shadow-gray-200/20">
            <div className="p-6 flex flex-col h-full">
              {/* Logo */}
              <div className="flex items-center gap-3 mb-8">
                <div className="bg-gradient-to-br from-indigo-500 to-purple-600 w-10 h-10 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-500/30">
                  <Zap className="w-5 h-5 text-white" />
                </div>
                <span className="text-xl font-bold bg-gradient-to-r from-gray-900 to-gray-600 bg-clip-text text-transparent">QPrisma</span>
              </div>

              <button
                onClick={() => setShowUpload(false)}
                className="w-full px-5 py-3.5 bg-gray-100 hover:bg-gray-200 rounded-xl transition-all text-sm font-semibold flex items-center gap-3 text-gray-700 mb-6 group"
              >
                <ChevronRight className="w-4 h-4 rotate-180 group-hover:-translate-x-1 transition-transform" />
                Back to Library
              </button>

              <div className="flex-1 overflow-y-auto space-y-1">
                <div className="px-3 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wider">Recent Uploads</div>
                {mediaList.slice(0, 5).map((item) => (
                  <button
                    key={item.id}
                    onClick={() => router.push(`/video/${item.id}`)}
                    className="w-full text-left px-3 py-2.5 hover:bg-indigo-50 rounded-lg transition-all group flex items-center gap-3"
                  >
                    <div className="w-2 h-2 rounded-full bg-gray-300 group-hover:bg-indigo-500 transition-colors"></div>
                    <p className="text-sm font-medium truncate text-gray-600 group-hover:text-indigo-600 transition-colors">
                      {item.original_filename}
                    </p>
                  </button>
                ))}
              </div>

              {/* User Section */}
              <div className="mt-auto pt-6 border-t border-gray-200/50 space-y-3">
                <div className="flex items-center gap-3 px-2">
                  <div className="w-9 h-9 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-indigo-500/30">
                    {user?.email?.substring(0, 2).toUpperCase() || 'U'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-900 truncate">{user?.full_name || 'User'}</p>
                    <p className="text-xs text-gray-500 truncate">{user?.email}</p>
                  </div>
                </div>
                <button
                  onClick={logout}
                  className="w-full px-4 py-2.5 bg-gray-100 hover:bg-red-50 rounded-xl text-gray-600 hover:text-red-600 transition-all font-medium flex items-center justify-center gap-2 text-sm"
                >
                  <LogOut className="w-4 h-4" />
                  Sign Out
                </button>
              </div>
            </div>
          </div>

          {/* Main Content - Upload */}
          <div className="flex-1 overflow-y-auto">
            <div className="max-w-2xl mx-auto p-12">
              <div className="mb-10">
                <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-indigo-100 text-indigo-700 rounded-full text-xs font-semibold mb-4">
                  <Sparkles className="w-3 h-3" />
                  AI-Powered Analysis
                </div>
                <h2 className="text-4xl font-bold text-gray-900 tracking-tight mb-3">
                  Upload Video
                </h2>
                <p className="text-lg text-gray-500">
                  Unlock intelligent insights from your video content.
                </p>
              </div>

              <div className="space-y-6">
                {/* Preset Selection */}
                <div className="bg-white rounded-2xl p-6 shadow-xl shadow-gray-200/50 border border-gray-100">
                  <label className="block text-sm font-semibold text-gray-700 mb-3">
                    Processing Preset
                  </label>
                  <div className="relative">
                    <select
                      value={selectedPreset}
                      onChange={(e) => setSelectedPreset(e.target.value)}
                      className="w-full px-4 py-3.5 bg-gray-50 text-gray-900 rounded-xl border-2 border-transparent focus:border-indigo-500 focus:bg-white focus:outline-none transition-all appearance-none text-base font-medium cursor-pointer hover:bg-gray-100"
                    >
                      {presets.map((preset) => (
                        <option key={preset.name} value={preset.name}>
                          {preset.name.replace(/_/g, ' ').toUpperCase()}
                        </option>
                      ))}
                    </select>
                    <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none">
                      <ChevronRight className="w-5 h-5 text-gray-400 rotate-90" />
                    </div>
                  </div>
                  <p className="mt-3 text-sm text-gray-500">
                    {presets.find(p => p.name === selectedPreset)?.description}
                  </p>
                </div>

                {/* Analysis Depth */}
                <div className="bg-white rounded-2xl p-6 shadow-xl shadow-gray-200/50 border border-gray-100">
                  <div className="flex items-center justify-between mb-4">
                    <label className="flex items-center gap-2 text-sm font-semibold text-gray-700">
                      <BarChart3 className="w-4 h-4 text-indigo-500" />
                      Analysis Depth
                    </label>
                    <span className="px-3 py-1 bg-gradient-to-r from-indigo-500 to-purple-500 text-white text-xs font-bold rounded-full shadow-lg shadow-indigo-500/30">
                      {maxFrames} Frames
                    </span>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="1000"
                    step="10"
                    value={maxFrames}
                    onChange={(e) => setMaxFrames(parseInt(e.target.value))}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                  />
                  <div className="flex justify-between text-xs text-gray-400 mt-3 font-medium">
                    <span>Quick Scan</span>
                    <span>Deep Analysis</span>
                  </div>
                </div>

                {/* Optimized Pipeline Toggle */}
                <div className="bg-white rounded-2xl p-6 shadow-xl shadow-gray-200/50 border border-gray-100">
                  <div className="flex items-center justify-between mb-4">
                    <label className="flex items-center gap-2 text-sm font-semibold text-gray-700">
                      <Cpu className="w-4 h-4 text-indigo-500" />
                      Processing Mode
                    </label>
                    <button
                      onClick={() => setUseOptimizedPipeline(!useOptimizedPipeline)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        useOptimizedPipeline ? 'bg-gradient-to-r from-indigo-500 to-purple-500' : 'bg-gray-300'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-lg transition-transform ${
                          useOptimizedPipeline ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>

                  <div className={`space-y-3 transition-all ${useOptimizedPipeline ? 'opacity-100' : 'opacity-50 pointer-events-none'}`}>
                    <p className="text-xs text-gray-500 mb-4">
                      Optimized pipeline uses scene detection and hierarchical summaries for faster processing and better search results.
                    </p>

                    {/* Scene Detection */}
                    <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div className="flex items-center gap-2">
                        <Layers className="w-4 h-4 text-indigo-400" />
                        <span className="text-sm font-medium text-gray-700">Scene Detection</span>
                      </div>
                      <button
                        onClick={() => setSceneDetectionEnabled(!sceneDetectionEnabled)}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                          sceneDetectionEnabled ? 'bg-indigo-500' : 'bg-gray-300'
                        }`}
                      >
                        <span
                          className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${
                            sceneDetectionEnabled ? 'translate-x-5' : 'translate-x-1'
                          }`}
                        />
                      </button>
                    </div>

                    {/* Hierarchical Summary */}
                    <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div className="flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-purple-400" />
                        <span className="text-sm font-medium text-gray-700">AI Summaries</span>
                      </div>
                      <button
                        onClick={() => setHierarchicalSummaryEnabled(!hierarchicalSummaryEnabled)}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                          hierarchicalSummaryEnabled ? 'bg-purple-500' : 'bg-gray-300'
                        }`}
                      >
                        <span
                          className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${
                            hierarchicalSummaryEnabled ? 'translate-x-5' : 'translate-x-1'
                          }`}
                        />
                      </button>
                    </div>
                  </div>

                  {useOptimizedPipeline && (
                    <div className="mt-4 p-3 bg-gradient-to-r from-indigo-50 to-purple-50 rounded-lg border border-indigo-100">
                      <div className="flex items-center gap-2 text-xs font-semibold text-indigo-700">
                        <Zap className="w-3 h-3" />
                        5-10x faster processing with scene-based analysis
                      </div>
                    </div>
                  )}
                </div>

                {/* Upload Component */}
                <VideoUpload
                  selectedPreset={selectedPreset}
                  maxFrames={maxFrames}
                  useOptimizedPipeline={useOptimizedPipeline}
                  sceneDetectionEnabled={sceneDetectionEnabled}
                  hierarchicalSummaryEnabled={hierarchicalSummaryEnabled}
                  onVideoProcessed={(mediaId) => {
                    router.push(`/video/${mediaId}`);
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30 font-sans selection:bg-indigo-100 selection:text-indigo-900">
      {/* Decorative Elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-gradient-to-br from-indigo-200/30 to-purple-200/30 rounded-full blur-3xl"></div>
        <div className="absolute bottom-0 -left-40 w-96 h-96 bg-gradient-to-br from-blue-200/20 to-cyan-200/20 rounded-full blur-3xl"></div>
      </div>

      <div className="relative flex min-h-screen">
        {/* Sidebar */}
        <div className="w-72 bg-white/70 backdrop-blur-xl border-r border-gray-200/50 flex flex-col sticky top-0 h-screen shadow-xl shadow-gray-200/20">
          <div className="p-6 flex flex-col h-full">
            {/* Logo */}
            <div className="flex items-center gap-3 mb-8">
              <div className="bg-gradient-to-br from-indigo-500 to-purple-600 w-10 h-10 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-500/30">
                <Zap className="w-5 h-5 text-white" />
              </div>
              <span className="text-xl font-bold bg-gradient-to-r from-gray-900 to-gray-600 bg-clip-text text-transparent">QPrisma</span>
            </div>

            {/* New Upload Button */}
            <button
              onClick={() => setShowUpload(true)}
              className="w-full px-5 py-3.5 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl transition-all font-semibold flex items-center justify-center gap-2 shadow-lg shadow-indigo-500/30 hover:shadow-xl hover:shadow-indigo-500/40 hover:-translate-y-0.5 mb-8"
            >
              <Plus className="w-5 h-5" />
              New Upload
            </button>

            {/* Navigation */}
            <div className="flex-1 overflow-y-auto -mx-2 px-2 space-y-1">
              <div className="px-3 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Library</div>

              <button className="w-full text-left px-4 py-3 bg-indigo-50 rounded-xl text-indigo-700 font-semibold flex items-center gap-3 border border-indigo-100">
                <Grid className="w-4 h-4" />
                All Videos
                <span className="ml-auto bg-indigo-500 text-white text-xs px-2 py-0.5 rounded-full font-bold">{mediaList.length}</span>
              </button>

              <button className="w-full text-left px-4 py-3 hover:bg-gray-100 rounded-xl text-gray-600 hover:text-gray-900 transition-all font-medium flex items-center gap-3">
                <Sparkles className="w-4 h-4" />
                Processed
                <span className="ml-auto text-gray-400 text-xs font-semibold">{processedCount}</span>
              </button>

              <button className="w-full text-left px-4 py-3 hover:bg-gray-100 rounded-xl text-gray-600 hover:text-gray-900 transition-all font-medium flex items-center gap-3">
                <Clock className="w-4 h-4" />
                Pending
                <span className="ml-auto text-gray-400 text-xs font-semibold">{pendingCount}</span>
              </button>
            </div>

            {/* User Section */}
            <div className="mt-auto pt-6 border-t border-gray-200/50 space-y-3">
              <div className="flex items-center gap-3 px-2">
                <div className="w-9 h-9 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-indigo-500/30">
                  {user?.email?.substring(0, 2).toUpperCase() || 'U'}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900 truncate">{user?.full_name || 'User'}</p>
                  <p className="text-xs text-gray-500 truncate">{user?.email}</p>
                </div>
              </div>
              <button
                onClick={logout}
                className="w-full px-4 py-2.5 bg-gray-100 hover:bg-red-50 rounded-xl text-gray-600 hover:text-red-600 transition-all font-medium flex items-center justify-center gap-2 text-sm"
              >
                <LogOut className="w-4 h-4" />
                Sign Out
              </button>
            </div>
          </div>
        </div>

        {/* Main Content Area */}
        <div className="flex-1 flex flex-col">
          {/* Header */}
          <div className="sticky top-0 z-10 bg-white/70 backdrop-blur-xl border-b border-gray-200/50">
            <div className="max-w-[1600px] mx-auto px-8 py-5">
              <div className="flex items-center justify-between gap-8">
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
                  <p className="text-sm text-gray-500 mt-0.5">Manage your video library</p>
                </div>

                <div className="flex-1 max-w-xl relative group">
                  <SearchIcon className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-indigo-500 transition-colors" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search videos..."
                    className="w-full pl-12 pr-4 py-3 bg-gray-100 border-2 border-transparent rounded-xl focus:border-indigo-500 focus:bg-white focus:outline-none transition-all text-gray-900 placeholder-gray-400"
                  />
                </div>

                <div className="flex items-center gap-2 bg-gray-100 p-1 rounded-lg">
                  <button
                    onClick={() => setViewMode('grid')}
                    className={`p-2 rounded-lg transition-all ${viewMode === 'grid' ? 'bg-white text-indigo-600 shadow' : 'text-gray-500 hover:text-gray-700'}`}
                  >
                    <Grid className="w-5 h-5" />
                  </button>
                  <button
                    onClick={() => setViewMode('list')}
                    className={`p-2 rounded-lg transition-all ${viewMode === 'list' ? 'bg-white text-indigo-600 shadow' : 'text-gray-500 hover:text-gray-700'}`}
                  >
                    <List className="w-5 h-5" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Video Grid */}
          <div className="flex-1 overflow-y-auto p-8">
            <div className="max-w-[1600px] mx-auto">
              {loadingMedia ? (
                <div className="flex items-center justify-center py-32">
                  <div className="text-center">
                    <div className="w-14 h-14 border-4 border-gray-200 border-t-indigo-500 rounded-full animate-spin mx-auto mb-6"></div>
                    <p className="text-gray-500 font-medium">Loading your library...</p>
                  </div>
                </div>
              ) : filteredMedia.length === 0 ? (
                <div className="flex items-center justify-center py-32">
                  <div className="text-center max-w-md">
                    <div className="bg-gradient-to-br from-indigo-100 to-purple-100 rounded-3xl w-28 h-28 flex items-center justify-center mx-auto mb-8 shadow-xl shadow-indigo-200/50">
                      <Video className="w-12 h-12 text-indigo-500" />
                    </div>
                    <h3 className="text-2xl font-bold text-gray-900 mb-3">
                      {searchQuery ? 'No videos found' : 'Start your journey'}
                    </h3>
                    <p className="text-gray-500 mb-8 leading-relaxed">
                      {searchQuery
                        ? 'Try adjusting your search terms'
                        : 'Upload your first video to unlock AI-powered insights and analytics.'
                      }
                    </p>
                    {!searchQuery && (
                      <button
                        onClick={() => setShowUpload(true)}
                        className="px-8 py-4 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-xl transition-all font-semibold flex items-center gap-2 mx-auto shadow-lg shadow-indigo-500/30 hover:shadow-xl hover:shadow-indigo-500/40 hover:-translate-y-0.5"
                      >
                        <Plus className="w-5 h-5" />
                        Upload Video
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-semibold text-gray-500">
                        {filteredMedia.length} {filteredMedia.length === 1 ? 'video' : 'videos'}
                      </span>
                    </div>
                  </div>

                  {viewMode === 'grid' ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-6">
                      {filteredMedia.map((item) => (
                        <div
                          key={item.id}
                          onClick={() => router.push(`/video/${item.id}`)}
                          className="group cursor-pointer bg-white rounded-2xl shadow-lg shadow-gray-200/50 border border-gray-100 overflow-hidden hover:shadow-xl hover:shadow-indigo-200/30 hover:-translate-y-1 transition-all duration-300"
                        >
                          {/* Thumbnail */}
                          <div className="aspect-video bg-gradient-to-br from-gray-100 to-gray-200 relative overflow-hidden">
                            <div className="absolute inset-0 flex items-center justify-center">
                              <Film className="w-12 h-12 text-gray-300" />
                            </div>

                            <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all duration-300 bg-gradient-to-t from-black/60 via-black/20 to-transparent">
                              <div className="bg-white text-indigo-600 rounded-full p-4 transform scale-90 group-hover:scale-100 transition-transform duration-300 shadow-xl">
                                <Play className="w-6 h-6 fill-indigo-600" />
                              </div>
                            </div>

                            {/* Status badge */}
                            <div className="absolute top-3 left-3">
                              {item.processed ? (
                                <div className="px-2.5 py-1 bg-green-500 text-white text-xs font-bold rounded-full shadow-lg flex items-center gap-1">
                                  <div className="w-1.5 h-1.5 bg-white rounded-full"></div>
                                  Ready
                                </div>
                              ) : (
                                <div className="px-2.5 py-1 bg-amber-500 text-white text-xs font-bold rounded-full shadow-lg flex items-center gap-1 animate-pulse">
                                  <div className="w-1.5 h-1.5 bg-white rounded-full"></div>
                                  Processing
                                </div>
                              )}
                            </div>

                            {/* Duration badge */}
                            {item.duration && (
                              <div className="absolute bottom-3 right-3">
                                <div className="px-2 py-1 bg-black/70 backdrop-blur text-white text-xs font-bold rounded-lg">
                                  {Math.floor(item.duration)}s
                                </div>
                              </div>
                            )}
                          </div>

                          {/* Info */}
                          <div className="p-4">
                            <div className="flex justify-between items-start mb-2">
                              <h3 className="font-semibold text-gray-900 truncate pr-3 group-hover:text-indigo-600 transition-colors">
                                {item.original_filename}
                              </h3>
                              <button
                                onClick={(e) => handleDelete(e, item.id)}
                                className="text-gray-400 hover:text-red-500 transition-colors p-1 hover:bg-red-50 rounded-lg"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>

                            <div className="flex items-center gap-2 text-xs text-gray-500">
                              <span>{formatDate(item.uploaded_at)}</span>
                              <span className="w-1 h-1 rounded-full bg-gray-300"></span>
                              <span>{formatFileSize(item.file_size)}</span>
                            </div>

                            {item.frames_analyzed && (
                              <div className="mt-3 flex items-center gap-2 text-xs font-medium text-indigo-600 bg-indigo-50 px-2 py-1 rounded-lg w-fit">
                                <Eye className="w-3 h-3" />
                                {item.frames_analyzed} frames analyzed
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {filteredMedia.map((item) => (
                        <div
                          key={item.id}
                          onClick={() => router.push(`/video/${item.id}`)}
                          className="group cursor-pointer bg-white rounded-xl shadow-lg shadow-gray-200/50 border border-gray-100 overflow-hidden hover:shadow-xl hover:shadow-indigo-200/30 transition-all duration-300 flex items-center gap-4 p-4"
                        >
                          {/* Thumbnail */}
                          <div className="w-32 h-20 bg-gradient-to-br from-gray-100 to-gray-200 rounded-lg relative overflow-hidden flex-shrink-0">
                            <div className="absolute inset-0 flex items-center justify-center">
                              <Film className="w-8 h-8 text-gray-300" />
                            </div>
                          </div>

                          {/* Info */}
                          <div className="flex-1 min-w-0">
                            <h3 className="font-semibold text-gray-900 truncate group-hover:text-indigo-600 transition-colors">
                              {item.original_filename}
                            </h3>
                            <div className="flex items-center gap-2 text-sm text-gray-500 mt-1">
                              <span>{formatDate(item.uploaded_at)}</span>
                              <span className="w-1 h-1 rounded-full bg-gray-300"></span>
                              <span>{formatFileSize(item.file_size)}</span>
                              {item.duration && (
                                <>
                                  <span className="w-1 h-1 rounded-full bg-gray-300"></span>
                                  <span>{Math.floor(item.duration)}s</span>
                                </>
                              )}
                            </div>
                          </div>

                          {/* Status */}
                          <div className="flex items-center gap-4">
                            {item.processed ? (
                              <div className="px-3 py-1.5 bg-green-100 text-green-700 text-xs font-bold rounded-full">
                                Ready
                              </div>
                            ) : (
                              <div className="px-3 py-1.5 bg-amber-100 text-amber-700 text-xs font-bold rounded-full animate-pulse">
                                Processing
                              </div>
                            )}

                            <button
                              onClick={(e) => handleDelete(e, item.id)}
                              className="text-gray-400 hover:text-red-500 transition-colors p-2 hover:bg-red-50 rounded-lg"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>

                            <ChevronRight className="w-5 h-5 text-gray-400 group-hover:text-indigo-500 group-hover:translate-x-1 transition-all" />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
