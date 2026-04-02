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
  X,
} from 'lucide-react';
import { formatTime } from '@/lib/utils';
import { VideoPanelTabs } from './VideoPanelTabs';
import type { TabType } from './VideoPanelTabs';

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

export interface CitationMarker {
  timestamp: number;
  type: 'visual' | 'audio' | 'entity';
}

interface VideoPanelProps {
  videoId?: string;
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
  citationMarkers?: CitationMarker[];
}

export default function VideoPanel({
  videoId,
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
  citationMarkers = [],
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
              {/* Citation markers — colored diamonds at cited timestamps */}
              {citationMarkers.map((marker, idx) => {
                const markerColors = {
                  visual: 'bg-indigo-400',
                  audio: 'bg-emerald-400',
                  entity: 'bg-amber-400',
                };
                return (
                  <div
                    key={`marker-${idx}-${marker.timestamp}`}
                    className={`absolute -top-1 w-2 h-2 rotate-45 ${markerColors[marker.type]} opacity-80 group-hover:opacity-100 transition-opacity pointer-events-none`}
                    style={{
                      left: `${(marker.timestamp / duration) * 100}%`,
                      marginLeft: '-4px',
                    }}
                    title={formatTime(marker.timestamp)}
                  />
                );
              })}
              <div
                className="absolute top-0 h-full bg-white rounded-full"
                style={{ width: `${(localCurrentTime / duration) * 100}%` }}
              />
              <div
                className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full shadow-lg opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ left: `${(localCurrentTime / duration) * 100}%`, marginLeft: '-6px' }}
              />
            </div>

            {/* Controls */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <button onClick={() => skip(-10)} className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors">
                  <SkipBack className="w-4 h-4" />
                </button>
                <button onClick={togglePlay} className="p-2 bg-white/20 hover:bg-white/30 rounded-lg text-white transition-colors">
                  {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
                </button>
                <button onClick={() => skip(10)} className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors">
                  <SkipForward className="w-4 h-4" />
                </button>
                <span className="text-white text-sm ml-2">
                  {formatTime(localCurrentTime)} / {formatTime(duration)}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button onClick={toggleMute} className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors">
                  {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
                </button>
                <button onClick={() => videoRef.current?.requestFullscreen()} className="p-2 hover:bg-white/20 rounded-lg text-white transition-colors">
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
              const colors = ['bg-indigo-400', 'bg-purple-400', 'bg-blue-400', 'bg-cyan-400', 'bg-teal-400'];

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

      {/* Tabs & Tab Content */}
      <VideoPanelTabs
        videoId={videoId}
        scenes={scenes}
        chapters={chapters}
        transcript={transcript}
        activeTab={activeTab}
        expandedChapter={expandedChapter}
        currentScene={currentScene}
        localCurrentTime={localCurrentTime}
        onTabChange={setActiveTab}
        onExpandChapter={setExpandedChapter}
        onSeek={handleSeek}
      />
    </div>
  );
}
