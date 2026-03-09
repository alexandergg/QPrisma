'use client';

import React, { useState, useEffect, useCallback, use, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { apiClient, EditorProjectWithClips, Clip } from '@/lib/api';
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
import { useEditorCallbacks } from './useEditorCallbacks';

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
    if (previewClip) return previewClip;
    if (activeClipId) return clips.find(c => c.id === activeClipId);
    return clips.find(c => currentTime >= c.start_time && currentTime <= c.end_time);
  }, [previewClip, activeClipId, clips, currentTime]);

  // Clip selected for subtitle editing
  const subtitleEditClip = useMemo(() => {
    if (!subtitleEditClipId) return undefined;
    return clips.find(c => c.id === subtitleEditClipId);
  }, [subtitleEditClipId, clips]);

  const fetchProject = useCallback(async () => {
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
  }, [resolvedParams.projectId]);

  useEffect(() => {
    fetchProject();
  }, [fetchProject]);

  // ── All handler callbacks ────────────────────────────────────────────────
  const handlers = useEditorCallbacks(
    {
      clips,
      activeClipId,
      subtitleEditClipId,
      subtitleEditClip,
      projectId: resolvedParams.projectId,
    },
    {
      setClips,
      setActiveClipId,
      setVideoSeekTime,
      setCurrentTime,
      setPreviewClip,
      setIsGeneratingClips,
      setSubtitleEditClipId,
      setExportClip,
      setExportModalOpen,
    },
    fetchProject,
  );

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
            <EditorVideoPanel
              videoUrl={project.source_media?.blob_url}
              videoTitle={project.source_media?.filename}
              duration={project.source_media?.duration}
              clips={clips}
              currentTime={videoSeekTime ?? currentTime}
              onTimeUpdate={handlers.handleTimeUpdate}
              onSeek={handlers.handleTimeUpdate}
              onClipClick={handlers.handleClipClickWithSubtitles}
              activeClipId={activeClipId}
              previewClip={previewClip}
              onPreviewEnd={handlers.handlePreviewEnd}
              subtitleData={activeClip?.subtitles_data}
              subtitlesEnabled={activeClip?.subtitles_enabled}
              activeClipStartTime={activeClip?.start_time}
              onSubtitleCueClick={handlers.handleSubtitleCueClick}
            />

            <TimelineWaveform
              videoUrl={project.source_media?.blob_url}
              duration={project.source_media?.duration || 0}
              clips={clips}
              currentTime={currentTime}
              onSeek={handlers.handleTimeUpdate}
              onClipClick={handlers.handleClipClick}
              onClipModify={handlers.handleClipModify}
              activeClipId={activeClipId}
            />

            <div className="flex-1 min-h-0 overflow-hidden border-t border-gray-200">
              <ClipsList
                clips={clips}
                activeClipId={activeClipId}
                onClipClick={handlers.handleClipClickWithSubtitles}
                onClipPlay={handlers.handleClipPlay}
                onClipDelete={handlers.handleClipDelete}
                onClipSubtitlesToggle={handlers.handleClipSubtitlesToggleWithEdit}
                onClipExport={handlers.handleClipExport}
                onExportAll={handlers.handleExportAllClips}
                onGenerateAutoClips={handlers.handleGenerateAutoClips}
                onClipsReorder={handlers.handleClipsReorder}
                isLoading={isGeneratingClips}
              />
            </div>

            {subtitleEditClip && subtitleEditClip.subtitles_enabled && (
              <div className="border-t border-gray-200 p-4 bg-gray-50">
                <SubtitleEditor
                  clip={subtitleEditClip}
                  onSubtitlesUpdated={handlers.handleSubtitlesUpdated}
                  currentTime={currentTime - subtitleEditClip.start_time}
                  onSeek={handlers.handleSubtitleSeek}
                />
              </div>
            )}
          </div>
        }
      >
        <EditorChat
          projectId={project.id}
          onClipsUpdated={handlers.handleClipsUpdated}
          onTimestampClick={handlers.handleTimestampClick}
        />
      </EditorLayout>

      <ExportModal
        isOpen={exportModalOpen}
        onClose={() => {
          setExportModalOpen(false);
          setExportClip(undefined);
        }}
        clip={exportClip}
        clips={exportClip ? undefined : clips}
        projectId={project.id}
        onExportComplete={handlers.handleExportComplete}
      />
    </RequireAuth>
  );
}
