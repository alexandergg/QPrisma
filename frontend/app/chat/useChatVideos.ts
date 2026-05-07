'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { apiClient } from '@/lib/api';
import { UPLOAD } from '@/lib/constants';
import type { VideoData, LibraryVideo, UploadingVideo } from './types';

/**
 * Hook managing video loading, selection, and multi-video state
 * for the chat page.
 */
export function useChatVideos() {
  const searchParams = useSearchParams();
  const urlVideoId = searchParams.get('videoId');
  const [selectedVideo, setSelectedVideo] = useState<VideoData | null>(null);
  const [selectedVideos, setSelectedVideos] = useState<VideoData[]>([]);
  const [currentTime, setCurrentTime] = useState(0);
  const [showVideoSelector, setShowVideoSelector] = useState(false);
  const [showMultiVideoSelector, setShowMultiVideoSelector] = useState(false);
  const [showUploader, setShowUploader] = useState(false);
  const [uploadingVideos, setUploadingVideos] = useState<UploadingVideo[]>([]);
  const [uploadPreset, setUploadPreset] = useState<string>('balanced');
  const [uploadMaxFrames, setUploadMaxFrames] = useState(200);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [activeVideoTab, setActiveVideoTab] = useState(0);
  const [comparisonMode, setComparisonMode] = useState<'tabs' | 'side-by-side'>('tabs');
  const [currentMode, setCurrentMode] = useState<'single' | 'library'>('single');
  const [isVideoLoading, setIsVideoLoading] = useState(false);
  const [videoLoadError, setVideoLoadError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const requestedUrlVideoIdRef = useRef<string | null>(null);

  const isMultiVideo = selectedVideos.length > 1;

  const loadVideo = useCallback(async (videoId: string): Promise<VideoData | null> => {
    try {
      const [metadata, structure] = await Promise.all([
        apiClient.getMediaById(videoId),
        apiClient.getVideoStructure(videoId).catch(() => null),
      ]);

      return {
        id: videoId,
        url: metadata.blob_url,
        title: metadata.original_filename,
        duration: metadata.duration,
        fileSize: metadata.file_size,
        uploadedAt: metadata.uploaded_at,
        thumbnailUrl: metadata.thumbnail_url,
        scenes: structure?.structure?.scenes || structure?.scenes || [],
        chapters: structure?.structure?.chapters || structure?.chapters || [],
        transcript: metadata.audio_data?.transcription?.segments || [],
      } as VideoData;
    } catch (error) {
      console.error('Failed to load video:', error);
      return null;
    }
  }, []);

  // Auto-load video from URL param
  useEffect(() => {
    if (!urlVideoId) {
      requestedUrlVideoIdRef.current = null;
      Promise.resolve().then(() => {
        setIsVideoLoading(false);
        setVideoLoadError(null);
      });
      return;
    }

    if (requestedUrlVideoIdRef.current === urlVideoId) {
      return;
    }

    let cancelled = false;
    requestedUrlVideoIdRef.current = urlVideoId;

    Promise.resolve().then(async () => {
      setIsVideoLoading(true);
      setVideoLoadError(null);
      setSelectedVideo(null);
      setSelectedVideos([]);
      setCurrentMode('single');

      const videoData = await loadVideo(urlVideoId);
      if (cancelled) return;

      if (videoData) {
        setSelectedVideo(videoData);
        setSelectedVideos([videoData]);
        setCurrentMode('single');
      } else {
        setVideoLoadError('Could not open this video. It may still be processing or unavailable.');
      }
      setIsVideoLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [urlVideoId, loadVideo, loadAttempt]);

  const handleSelectVideoFromLibrary = async (video: LibraryVideo) => {
    setShowVideoSelector(false);
    const videoData = await loadVideo(video.id);
    if (videoData) {
      setSelectedVideo(videoData);
      setSelectedVideos([videoData]);
    }
  };

  const handleMultiVideoSelectionChange = async (ids: string[]) => {
    const limitedIds = ids.slice(0, UPLOAD.MAX_FILES);
    const videos: VideoData[] = [];
    for (const id of limitedIds) {
      const existing = selectedVideos.find((v) => v.id === id);
      if (existing) {
        videos.push(existing);
      } else {
        const videoData = await loadVideo(id);
        if (videoData) videos.push(videoData);
      }
    }
    setSelectedVideos(videos);
    if (videos.length >= 1) {
      setSelectedVideo(videos[0]);
    } else {
      setSelectedVideo(null);
    }
  };

  const handleConfirmMultiSelect = () => {
    setShowMultiVideoSelector(false);
    if (selectedVideos.length > 1) setCurrentMode('library');
  };

  const handleRemoveVideo = (videoId: string) => {
    const updated = selectedVideos.filter((v) => v.id !== videoId);
    setSelectedVideos(updated);
    if (updated.length !== 2) setComparisonMode('tabs');
    if (activeVideoTab >= updated.length) {
      setActiveVideoTab(Math.max(0, updated.length - 1));
    }
    if (updated.length === 0) {
      setSelectedVideo(null);
      setCurrentMode('single');
    } else if (updated.length === 1) {
      setSelectedVideo(updated[0]);
      setCurrentMode('single');
    } else {
      setSelectedVideo(updated[0]);
    }
  };

  const handleUploadComplete = async (mediaId: string) => {
    setShowUploader(false);
    const videoData = await loadVideo(mediaId);
    if (videoData) {
      setSelectedVideo(videoData);
      setSelectedVideos([videoData]);
      setCurrentMode('single');
    }
  };

  const handleSelectVideoById = useCallback(
    async (videoId: string) => {
      const videoData = await loadVideo(videoId);
      if (videoData) {
        setSelectedVideo(videoData);
        setSelectedVideos([videoData]);
      }
    },
    [loadVideo],
  );

  const clearSelection = () => {
    requestedUrlVideoIdRef.current = null;
    setIsVideoLoading(false);
    setVideoLoadError(null);
    setSelectedVideo(null);
    setSelectedVideos([]);
  };

  const retryUrlVideoLoad = useCallback(() => {
    requestedUrlVideoIdRef.current = null;
    setVideoLoadError(null);
    setLoadAttempt((attempt) => attempt + 1);
  }, []);

  const isOpeningUrlVideo = Boolean(
    urlVideoId &&
      !videoLoadError &&
      (isVideoLoading || selectedVideo?.id !== urlVideoId),
  );

  return {
    selectedVideo,
    selectedVideos,
    currentTime,
    showVideoSelector,
    showMultiVideoSelector,
    showUploader,
    uploadingVideos,
    uploadPreset,
    uploadMaxFrames,
    pendingFiles,
    activeVideoTab,
    comparisonMode,
    currentMode,
    isMultiVideo,
    pendingVideoId: urlVideoId,
    isVideoLoading: isOpeningUrlVideo,
    videoLoadError,
    setSelectedVideo,
    setCurrentTime,
    setShowVideoSelector,
    setShowMultiVideoSelector,
    setShowUploader,
    setUploadingVideos,
    setUploadPreset,
    setUploadMaxFrames,
    setPendingFiles,
    setActiveVideoTab,
    setComparisonMode,
    setCurrentMode,
    handleSelectVideoFromLibrary,
    handleMultiVideoSelectionChange,
    handleConfirmMultiSelect,
    handleRemoveVideo,
    handleUploadComplete,
    handleSelectVideoById,
    clearSelection,
    retryUrlVideoLoad,
  };
}
