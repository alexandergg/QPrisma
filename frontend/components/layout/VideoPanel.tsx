'use client';

import React, { useRef, useEffect, useState } from 'react';
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize,
  SkipBack,
  SkipForward,
  Layers,
  Mic,
  ChevronDown,
  ChevronRight,
  X,
} from 'lucide-react';
import { formatTime } from '@/lib/utils';

interface Scene {
  scene_id: number;
  start_time: number;
  end_time: number;
  duration?: number;
  title?: string;
  summary?: string;
}

interface Chapter {
  chapter_id: number;
  title: string;
  start_time: number;
  end_time: number;
  scene_ids?: number[];
}

interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  text: string;
}

interface VideoPanelProps {
  videoUrl?: string;
  videoTitle?: string;
  duration?: number;
  scenes?: Scene[];
  chapters?: Chapter[];
  transcript?: TranscriptSegment[];
  currentTime?: number;
  onTimeUpdate?: (time: number) => void;
  onSeek?: (time: number) => void;
  isVisible?: boolean;
  onClose?: () => void;
}

type TabType = 'chapters' | 'transcript' | 'entities';

export default function VideoPanel({
  videoUrl,
  videoTitle,
  duration = 0,
  scenes = [],
  chapters = [],
  transcript = [],
  currentTime = 0,
  onTimeUpdate,
  onSeek,
  isVisible = true,
  onClose,
}: VideoPanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [localCurrentTime, setLocalCurrentTime] = useState(currentTime);
  const [activeTab, setActiveTab] = useState<TabType>('chapters');
  const [expandedChapter, setExpandedChapter] = useState<number | null>(0);

  // Sync external currentTime
  useEffect(() => {
    if (Math.abs(currentTime - localCurrentTime) > 1) {
      if (videoRef.current) {
        videoRef.current.currentTime = currentTime;
      }
    }
  }, [currentTime, localCurrentTime]);

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      const time = videoRef.current.currentTime;
      setLocalCurrentTime(time);
      onTimeUpdate?.(time);
    }
  };

  const handleSeek = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      setLocalCurrentTime(time);
      onSeek?.(time);
    }
  };

  const togglePlay = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const toggleMute = () => {
    if (videoRef.current) {
      videoRef.current.muted = !isMuted;
      setIsMuted(!isMuted);
    }
  };

  const skip = (seconds: number) => {
    if (videoRef.current) {
      const newTime = Math.max(0, Math.min(duration, videoRef.current.currentTime + seconds));
      handleSeek(newTime);
    }
  };

  // Find current scene
  const currentScene = scenes.find(
    (s) => localCurrentTime >= s.start_time && localCurrentTime < s.end_time
  );

  if (!isVisible) return null;

  return (
    <div className="w-full h-full flex flex-col bg-white border-l border-gray-200">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 truncate">{videoTitle || 'Video'}</h3>
        {onClose && (
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Video Player */}
      <div className="relative bg-black aspect-video">
        {videoUrl ? (
          <video
            ref={videoRef}
            src={videoUrl}
            className="w-full h-full object-contain"
            onTimeUpdate={handleTimeUpdate}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-500">
            <p>No video selected</p>
          </div>
        )}

        {/* Video Controls Overlay */}
        {videoUrl && (
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4">
            {/* Progress Bar */}
            <div
              className="relative h-1.5 bg-white/30 rounded-full mb-3 cursor-pointer group"
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const percent = (e.clientX - rect.left) / rect.width;
                handleSeek(percent * duration);
              }}
            >
              {/* Scene markers */}
              {scenes.map((scene) => (
                <div
                  key={scene.scene_id}
                  className="absolute top-0 h-full bg-indigo-400/50"
                  style={{
                    left: `${(scene.start_time / duration) * 100}%`,
                    width: `${((scene.end_time - scene.start_time) / duration) * 100}%`,
                  }}
                />
              ))}
              {/* Progress */}
              <div
                className="absolute top-0 h-full bg-white rounded-full"
                style={{ width: `${(localCurrentTime / duration) * 100}%` }}
              />
              {/* Handle */}
              <div
                className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full shadow-lg opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ left: `${(localCurrentTime / duration) * 100}%`, marginLeft: '-6px' }}
              />
            </div>

            {/* Controls */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => skip(-10)}
                  className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
                >
                  <SkipBack className="w-4 h-4" />
                </button>
                <button
                  onClick={togglePlay}
                  className="p-2 bg-white/20 hover:bg-white/30 rounded-lg text-white transition-colors"
                >
                  {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
                </button>
                <button
                  onClick={() => skip(10)}
                  className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
                >
                  <SkipForward className="w-4 h-4" />
                </button>
                <span className="text-white text-sm ml-2">
                  {formatTime(localCurrentTime)} / {formatTime(duration)}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={toggleMute}
                  className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
                >
                  {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
                </button>
                <button
                  onClick={() => videoRef.current?.requestFullscreen()}
                  className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors"
                >
                  <Maximize className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Scene Timeline */}
      {scenes.length > 0 && (
        <div className="px-4 py-3 border-b border-gray-100">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-500 uppercase">Scene Timeline</span>
            {currentScene && (
              <span className="text-xs text-indigo-600 font-medium">
                {currentScene.title || `Scene ${currentScene.scene_id + 1}`}
              </span>
            )}
          </div>
          <div className="flex gap-1 h-2">
            {scenes.map((scene, idx) => {
              const width = ((scene.end_time - scene.start_time) / duration) * 100;
              const isActive = currentScene?.scene_id === scene.scene_id;
              const colors = [
                'bg-indigo-400',
                'bg-purple-400',
                'bg-blue-400',
                'bg-cyan-400',
                'bg-teal-400',
              ];

              return (
                <div
                  key={scene.scene_id}
                  className={`h-full rounded-full cursor-pointer transition-all ${
                    colors[idx % colors.length]
                  } ${isActive ? 'ring-2 ring-white ring-offset-1' : 'opacity-60 hover:opacity-100'}`}
                  style={{ width: `${Math.max(width, 2)}%` }}
                  onClick={() => handleSeek(scene.start_time)}
                  title={scene.title || `Scene ${scene.scene_id + 1}`}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-gray-100">
        <button
          onClick={() => setActiveTab('chapters')}
          className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors ${
            activeTab === 'chapters'
              ? 'text-indigo-600 border-b-2 border-indigo-600'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          <Layers className="w-4 h-4" />
          Chapters
        </button>
        <button
          onClick={() => setActiveTab('transcript')}
          className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors ${
            activeTab === 'transcript'
              ? 'text-indigo-600 border-b-2 border-indigo-600'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          <Mic className="w-4 h-4" />
          Transcript
        </button>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'chapters' && (
          <div className="p-3 space-y-2">
            {chapters.length === 0 && scenes.length === 0 ? (
              <div className="text-center py-8">
                <Layers className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                <p className="text-sm text-gray-500">No chapters available</p>
              </div>
            ) : chapters.length === 0 ? (
              // Show scenes if no chapters
              scenes.map((scene) => {
                const isActive = currentScene?.scene_id === scene.scene_id;

                return (
                  <button
                    key={scene.scene_id}
                    onClick={() => handleSeek(scene.start_time)}
                    className={`w-full text-left p-3 rounded-xl transition-all flex items-center gap-3 ${
                      isActive ? 'bg-indigo-50 border-l-4 border-indigo-500' : 'hover:bg-gray-50'
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
                );
              })
            ) : (
              // Show chapters with nested scenes
              chapters.map((chapter) => {
                const isExpanded = expandedChapter === chapter.chapter_id;
                const chapterScenes = scenes.filter((s) => chapter.scene_ids?.includes(s.scene_id));
                const isActive = chapterScenes.some((s) => currentScene?.scene_id === s.scene_id);

                return (
                  <div key={chapter.chapter_id} className="rounded-xl overflow-hidden bg-gray-50">
                    <button
                      onClick={() => setExpandedChapter(isExpanded ? null : chapter.chapter_id)}
                      className={`w-full text-left p-3 flex items-center gap-3 transition-all ${
                        isActive ? 'bg-indigo-50' : 'hover:bg-gray-100'
                      }`}
                    >
                      {isExpanded ? (
                        <ChevronDown className="w-4 h-4 text-gray-400" />
                      ) : (
                        <ChevronRight className="w-4 h-4 text-gray-400" />
                      )}
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm font-medium ${isActive ? 'text-indigo-700' : 'text-gray-700'}`}>
                          {chapter.title}
                        </p>
                        <p className="text-xs text-gray-400">
                          {formatTime(chapter.start_time)} • {chapterScenes.length} scenes
                        </p>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSeek(chapter.start_time);
                        }}
                        className="p-1.5 hover:bg-indigo-100 rounded-lg text-indigo-500"
                      >
                        <Play className="w-3 h-3 fill-current" />
                      </button>
                    </button>

                    {isExpanded && chapterScenes.length > 0 && (
                      <div className="px-3 pb-3 space-y-1">
                        {chapterScenes.map((scene) => {
                          const isSceneActive = currentScene?.scene_id === scene.scene_id;

                          return (
                            <button
                              key={scene.scene_id}
                              onClick={() => handleSeek(scene.start_time)}
                              className={`w-full text-left pl-8 pr-3 py-2 rounded-lg transition-all text-sm ${
                                isSceneActive
                                  ? 'bg-indigo-100 text-indigo-700 font-medium'
                                  : 'text-gray-600 hover:bg-white'
                              }`}
                            >
                              <span className="text-gray-400 mr-2">{formatTime(scene.start_time)}</span>
                              {scene.title || `Scene ${scene.scene_id + 1}`}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}

        {activeTab === 'transcript' && (
          <div className="p-3 space-y-2">
            {transcript.length === 0 ? (
              <div className="text-center py-8">
                <Mic className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                <p className="text-sm text-gray-500">No transcript available</p>
              </div>
            ) : (
              transcript.map((segment) => {
                const isActive = localCurrentTime >= segment.start && localCurrentTime < segment.end;

                return (
                  <button
                    key={segment.id}
                    onClick={() => handleSeek(segment.start)}
                    className={`w-full text-left p-3 rounded-xl transition-all ${
                      isActive ? 'bg-indigo-50 border-l-4 border-indigo-500' : 'hover:bg-gray-50'
                    }`}
                  >
                    <span className="text-xs text-indigo-500 font-medium">
                      {formatTime(segment.start)}
                    </span>
                    <p className={`text-sm mt-1 ${isActive ? 'text-indigo-700 font-medium' : 'text-gray-700'}`}>
                      {segment.text}
                    </p>
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
}
