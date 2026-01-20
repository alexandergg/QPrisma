'use client';

import React, { useState, useEffect, useCallback, use, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { apiClient, EditorProjectWithClips, Clip, ExportResult } from '@/lib/api';
import RequireAuth from '@/components/RequireAuth';
import {
  EditorLayout,
  EditorVideoPanel,
  EditorChat,
  ClipsList,
  TimelineWaveform,
  SubtitleEditor,
  ExportModal,
} from '@/components/editor';
import { SubtitleCue } from '@/components/editor/SubtitleOverlay';

interface PageParams {
  params: Promise<{
    projectId: string;
  }>;
}

/**
 * Editor project detail page with Chat-to-Edit interface
 */
export default function EditorProjectPage({ params }: PageParams) {
  const resolvedParams = use(params);
  const router = useRouter();
  const [project, setProject] = useState<EditorProjectWithClips | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [activeClipId, setActiveClipId] = useState<string | undefined>();
  const [videoSeekTime, setVideoSeekTime] = useState<number | undefined>();
  const [isGeneratingClips, setIsGeneratingClips] = useState(false);
  const [previewClip, setPreviewClip] = useState<Clip | undefined>();
  const [subtitleEditClipId, setSubtitleEditClipId] = useState<string | undefined>();
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportClip, setExportClip] = useState<Clip | undefined>();

  // Find the active clip for subtitle display
  const activeClip = useMemo(() => {
    // Priority: previewClip > activeClipId > clip under playhead
    if (previewClip) return previewClip;
    if (activeClipId) return clips.find(c => c.id === activeClipId);
    // Find clip under current playhead
    return clips.find(c => currentTime >= c.start_time && currentTime <= c.end_time);
  }, [previewClip, activeClipId, clips, currentTime]);

  // Clip selected for subtitle editing
  const subtitleEditClip = useMemo(() => {
    if (!subtitleEditClipId) return undefined;
    return clips.find(c => c.id === subtitleEditClipId);
  }, [subtitleEditClipId, clips]);

  // Fetch project on mount
  useEffect(() => {
    fetchProject();
  }, [resolvedParams.projectId]);

  const fetchProject = async () => {
    try {
      setIsLoading(true);
      const data = await apiClient.getEditorProject(resolvedParams.projectId);
      setProject(data);
      setClips(data.clips || []);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch project:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch project');
    } finally {
      setIsLoading(false);
    }
  };

  // Handle clips updated from chat
  const handleClipsUpdated = useCallback((updatedClips: Clip[]) => {
    setClips(updatedClips);
  }, []);

  // Handle timestamp click in chat
  const handleTimestampClick = useCallback((timestamp: number) => {
    setVideoSeekTime(timestamp);
    setCurrentTime(timestamp);
  }, []);

  // Handle time update from video
  const handleTimeUpdate = useCallback((time: number) => {
    setCurrentTime(time);
    setVideoSeekTime(undefined);
  }, []);

  // Handle clip click
  const handleClipClick = useCallback((clip: Clip) => {
    setActiveClipId(clip.id);
    setVideoSeekTime(clip.start_time);
  }, []);

  // Handle clip play (preview mode - plays only the clip segment)
  const handleClipPlay = useCallback((clip: Clip) => {
    setActiveClipId(clip.id);
    setPreviewClip(clip);
  }, []);

  // Handle preview end
  const handlePreviewEnd = useCallback(() => {
    setPreviewClip(undefined);
  }, []);

  // Handle clip delete
  const handleClipDelete = useCallback(async (clip: Clip) => {
    if (!confirm('Delete this clip?')) return;

    try {
      await apiClient.deleteClip(clip.id);
      setClips((prev) => prev.filter((c) => c.id !== clip.id));
      if (activeClipId === clip.id) {
        setActiveClipId(undefined);
      }
    } catch (err) {
      console.error('Failed to delete clip:', err);
      alert('Failed to delete clip');
    }
  }, [activeClipId]);

  // Handle clip subtitles toggle
  const handleClipSubtitlesToggle = useCallback(async (clip: Clip) => {
    try {
      const updated = await apiClient.updateClipSubtitles(clip.id, {
        enabled: !clip.subtitles_enabled,
        style: clip.subtitles_enabled ? undefined : 'hormozi',
      });
      setClips((prev) =>
        prev.map((c) => (c.id === clip.id ? updated : c))
      );
    } catch (err) {
      console.error('Failed to toggle subtitles:', err);
    }
  }, []);

  // Handle clip modification from timeline drag
  const handleClipModify = useCallback(async (clipId: string, startTime: number, endTime: number) => {
    try {
      const updated = await apiClient.updateClip(clipId, {
        start_time: startTime,
        end_time: endTime,
      });
      setClips((prev) =>
        prev.map((c) => (c.id === clipId ? updated : c))
      );
    } catch (err) {
      console.error('Failed to modify clip:', err);
      alert('Failed to modify clip');
    }
  }, []);

  // Handle clips reorder from drag & drop
  const handleClipsReorder = useCallback(async (clipOrders: { clip_id: string; order: number }[]) => {
    // Optimistic update
    setClips((prev) => {
      const newClips = [...prev];
      clipOrders.forEach(({ clip_id, order }) => {
        const clip = newClips.find((c) => c.id === clip_id);
        if (clip) {
          clip.order = order;
        }
      });
      return newClips.sort((a, b) => a.order - b.order);
    });

    try {
      await apiClient.reorderClips(resolvedParams.projectId, clipOrders);
    } catch (err) {
      console.error('Failed to reorder clips:', err);
      // Revert on error
      fetchProject();
    }
  }, [resolvedParams.projectId]);

  // Handle generate auto-clips (this would be done via chat in practice)
  const handleGenerateAutoClips = useCallback(() => {
    // This is just a placeholder - the actual generation is done via chat
    // Could pre-fill the chat input with a suggestion
    setIsGeneratingClips(true);
    // Show some feedback
    setTimeout(() => setIsGeneratingClips(false), 500);
  }, []);

  // Handle subtitle cue click (for editing)
  const handleSubtitleCueClick = useCallback((cue: SubtitleCue) => {
    // Could open an inline editor or scroll to cue in SubtitleEditor
    console.log('Subtitle cue clicked:', cue);
  }, []);

  // Handle subtitles updated from SubtitleEditor
  const handleSubtitlesUpdated = useCallback((updatedClip: Clip) => {
    setClips((prev) =>
      prev.map((c) => (c.id === updatedClip.id ? updatedClip : c))
    );
  }, []);

  // Handle subtitle seek (from SubtitleEditor cue click)
  const handleSubtitleSeek = useCallback((relativeTime: number) => {
    // Convert relative time to absolute time
    if (subtitleEditClip) {
      const absoluteTime = subtitleEditClip.start_time + relativeTime;
      setVideoSeekTime(absoluteTime);
      setCurrentTime(absoluteTime);
    }
  }, [subtitleEditClip]);

  // When a clip is clicked, also select it for subtitle editing if it has subtitles
  const handleClipClickWithSubtitles = useCallback((clip: Clip) => {
    handleClipClick(clip);
    if (clip.subtitles_enabled) {
      setSubtitleEditClipId(clip.id);
    }
  }, [handleClipClick]);

  // Toggle subtitle editing for a clip
  const handleClipSubtitlesToggleWithEdit = useCallback(async (clip: Clip) => {
    await handleClipSubtitlesToggle(clip);
    // If enabling subtitles, open the editor
    if (!clip.subtitles_enabled) {
      setSubtitleEditClipId(clip.id);
    } else {
      // If disabling and this is the edit clip, clear it
      if (subtitleEditClipId === clip.id) {
        setSubtitleEditClipId(undefined);
      }
    }
  }, [handleClipSubtitlesToggle, subtitleEditClipId]);

  // Handle export clip
  const handleClipExport = useCallback((clip: Clip) => {
    setExportClip(clip);
    setExportModalOpen(true);
  }, []);

  // Handle export all clips
  const handleExportAllClips = useCallback(() => {
    setExportClip(undefined); // No single clip = batch mode
    setExportModalOpen(true);
  }, []);

  // Handle export complete
  const handleExportComplete = useCallback((_result: ExportResult | ExportResult[]) => {
    // Refresh clips to get updated export status
    fetchProject();
  }, []);

  if (isLoading) {
    return (
      <RequireAuth>
        <div className="flex items-center justify-center h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30">
          <div className="flex flex-col items-center">
            <Loader2 className="w-10 h-10 text-indigo-500 animate-spin mb-4" />
            <p className="text-gray-500">Loading project...</p>
          </div>
        </div>
      </RequireAuth>
    );
  }

  if (error || !project) {
    return (
      <RequireAuth>
        <div className="flex items-center justify-center h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30">
          <div className="flex flex-col items-center text-center">
            <p className="text-red-500 mb-4">{error || 'Project not found'}</p>
            <button
              onClick={() => router.push('/editor')}
              className="px-4 py-2 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 transition-colors"
            >
              Back to Projects
            </button>
          </div>
        </div>
      </RequireAuth>
    );
  }

  return (
    <RequireAuth>
      <EditorLayout
        projectName={project.name}
        videoPanel={
          <div className="flex flex-col h-full">
            {/* Video Panel */}
            <EditorVideoPanel
              videoUrl={project.source_media?.blob_url}
              videoTitle={project.source_media?.filename}
              duration={project.source_media?.duration}
              clips={clips}
              currentTime={videoSeekTime ?? currentTime}
              onTimeUpdate={handleTimeUpdate}
              onSeek={handleTimeUpdate}
              onClipClick={handleClipClickWithSubtitles}
              activeClipId={activeClipId}
              previewClip={previewClip}
              onPreviewEnd={handlePreviewEnd}
              subtitleData={activeClip?.subtitles_data}
              subtitlesEnabled={activeClip?.subtitles_enabled}
              activeClipStartTime={activeClip?.start_time}
              onSubtitleCueClick={handleSubtitleCueClick}
            />

            {/* Timeline with Waveform */}
            <TimelineWaveform
              videoUrl={project.source_media?.blob_url}
              duration={project.source_media?.duration || 0}
              clips={clips}
              currentTime={currentTime}
              onSeek={handleTimeUpdate}
              onClipClick={handleClipClick}
              onClipModify={handleClipModify}
              activeClipId={activeClipId}
            />

            {/* Clips List */}
            <div className="flex-1 min-h-0 overflow-hidden border-t border-gray-200">
              <ClipsList
                clips={clips}
                activeClipId={activeClipId}
                onClipClick={handleClipClickWithSubtitles}
                onClipPlay={handleClipPlay}
                onClipDelete={handleClipDelete}
                onClipSubtitlesToggle={handleClipSubtitlesToggleWithEdit}
                onClipExport={handleClipExport}
                onExportAll={handleExportAllClips}
                onGenerateAutoClips={handleGenerateAutoClips}
                onClipsReorder={handleClipsReorder}
                isLoading={isGeneratingClips}
              />
            </div>

            {/* Subtitle Editor */}
            {subtitleEditClip && subtitleEditClip.subtitles_enabled && (
              <div className="border-t border-gray-200 p-4 bg-gray-50">
                <SubtitleEditor
                  clip={subtitleEditClip}
                  onSubtitlesUpdated={handleSubtitlesUpdated}
                  currentTime={currentTime - subtitleEditClip.start_time}
                  onSeek={handleSubtitleSeek}
                />
              </div>
            )}
          </div>
        }
      >
        {/* Chat Panel */}
        <EditorChat
          projectId={project.id}
          onClipsUpdated={handleClipsUpdated}
          onTimestampClick={handleTimestampClick}
        />
      </EditorLayout>

      {/* Export Modal */}
      <ExportModal
        isOpen={exportModalOpen}
        onClose={() => {
          setExportModalOpen(false);
          setExportClip(undefined);
        }}
        clip={exportClip}
        clips={exportClip ? undefined : clips}
        projectId={project.id}
        onExportComplete={handleExportComplete}
      />
    </RequireAuth>
  );
}
