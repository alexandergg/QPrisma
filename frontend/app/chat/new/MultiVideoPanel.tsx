'use client';

import React from 'react';
import { Film, Columns2 } from 'lucide-react';
import { VideoPanel } from '@/components/layout';
import type { VideoData } from '../types';

interface MultiVideoPanelProps {
  selectedVideos: VideoData[];
  activeVideoTab: number;
  comparisonMode: 'tabs' | 'side-by-side';
  currentTime: number;
  onActiveVideoTabChange: (index: number) => void;
  onSelectedVideoChange: (video: VideoData) => void;
  onComparisonModeToggle: () => void;
  onTimeUpdate: (time: number) => void;
  onRemoveVideo: (videoId: string) => void;
}

export default function MultiVideoPanel({
  selectedVideos,
  activeVideoTab,
  comparisonMode,
  currentTime,
  onActiveVideoTabChange,
  onSelectedVideoChange,
  onComparisonModeToggle,
  onTimeUpdate,
  onRemoveVideo,
}: MultiVideoPanelProps) {
  return (
    <div className="w-full md:w-[40%] md:min-w-[400px] md:max-w-[600px] flex-shrink-0 h-[40vh] md:h-screen flex flex-col">
      {/* Video Tabs */}
      <div className="flex border-b border-gray-200 bg-white overflow-x-auto">
        {selectedVideos.map((v, idx) => (
          <button
            key={v.id}
            onClick={() => {
              onActiveVideoTabChange(idx);
              onSelectedVideoChange(v);
            }}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-colors ${
              activeVideoTab === idx
                ? 'border-purple-500 text-purple-700 bg-purple-50/50'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}
          >
            <Film className="w-3.5 h-3.5" />
            <span className="max-w-[100px] truncate">{v.title}</span>
          </button>
        ))}
        {selectedVideos.length === 2 && (
          <button
            onClick={onComparisonModeToggle}
            className={`ml-auto flex items-center gap-1.5 px-3 py-2 text-xs whitespace-nowrap border-b-2 transition-colors ${
              comparisonMode === 'side-by-side'
                ? 'border-purple-500 text-purple-700 bg-purple-50/50'
                : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}
            title="Toggle side-by-side view"
          >
            <Columns2 className="w-3.5 h-3.5" />
            <span>Compare</span>
          </button>
        )}
      </div>

      {/* Video Content */}
      {comparisonMode === 'side-by-side' && selectedVideos.length === 2 ? (
        <div className="flex-1 min-h-0 flex flex-col">
          {selectedVideos.map((v) => (
            <div key={v.id} className="flex-1 min-h-0 border-b border-gray-200 last:border-b-0">
              <VideoPanel
                videoId={v.id}
                videoUrl={v.url}
                videoTitle={v.title}
                duration={v.duration}
                scenes={v.scenes}
                chapters={v.chapters}
                transcript={v.transcript}
                currentTime={currentTime}
                onTimeUpdate={onTimeUpdate}
                onSeek={onTimeUpdate}
                isVisible={true}
                onClose={() => onRemoveVideo(v.id)}
              />
            </div>
          ))}
        </div>
      ) : selectedVideos[activeVideoTab] ? (
        <div className="flex-1 min-h-0">
          <VideoPanel
            videoId={selectedVideos[activeVideoTab].id}
            videoUrl={selectedVideos[activeVideoTab].url}
            videoTitle={selectedVideos[activeVideoTab].title}
            duration={selectedVideos[activeVideoTab].duration}
            scenes={selectedVideos[activeVideoTab].scenes}
            chapters={selectedVideos[activeVideoTab].chapters}
            transcript={selectedVideos[activeVideoTab].transcript}
            currentTime={currentTime}
            onTimeUpdate={onTimeUpdate}
            onSeek={onTimeUpdate}
            isVisible={true}
            onClose={() => onRemoveVideo(selectedVideos[activeVideoTab].id)}
          />
        </div>
      ) : null}
    </div>
  );
}
