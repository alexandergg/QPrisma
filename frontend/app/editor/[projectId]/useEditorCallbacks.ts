'use client';

import { useCallback } from 'react';
import { apiClient, Clip } from '@/lib/api';
import type { SubtitleCue } from '@/components/editor/SubtitleOverlay';

// ── State shape expected by the hook ──────────────────────────────────────

interface EditorState {
  clips: Clip[];
  activeClipId?: string;
  subtitleEditClipId?: string;
  subtitleEditClip?: Clip;
  projectId: string;
}

interface EditorSetters {
  setClips: React.Dispatch<React.SetStateAction<Clip[]>>;
  setActiveClipId: React.Dispatch<React.SetStateAction<string | undefined>>;
  setVideoSeekTime: React.Dispatch<React.SetStateAction<number | undefined>>;
  setCurrentTime: React.Dispatch<React.SetStateAction<number>>;
  setPreviewClip: React.Dispatch<React.SetStateAction<Clip | undefined>>;
  setIsGeneratingClips: React.Dispatch<React.SetStateAction<boolean>>;
  setSubtitleEditClipId: React.Dispatch<React.SetStateAction<string | undefined>>;
  setExportClip: React.Dispatch<React.SetStateAction<Clip | undefined>>;
  setExportModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

// ── Hook ──────────────────────────────────────────────────────────────────

/**
 * Consolidates all editor page callback handlers.
 *
 * This keeps the page component focused on state declarations, data
 * fetching, and rendering while this hook owns the behavioural logic.
 */
export function useEditorCallbacks(
  state: EditorState,
  setters: EditorSetters,
  fetchProject: () => Promise<void>,
) {
  const {
    clips,
    activeClipId,
    subtitleEditClipId,
    subtitleEditClip,
    projectId,
  } = state;

  const {
    setClips,
    setActiveClipId,
    setVideoSeekTime,
    setCurrentTime,
    setPreviewClip,
    setIsGeneratingClips,
    setSubtitleEditClipId,
    setExportClip,
    setExportModalOpen,
  } = setters;

  // ── Clip selection / navigation ────────────────────────────────────────

  const handleClipsUpdated = useCallback(
    (updatedClips: Clip[]) => setClips(updatedClips),
    [setClips],
  );

  const handleTimestampClick = useCallback(
    (timestamp: number) => {
      setVideoSeekTime(timestamp);
      setCurrentTime(timestamp);
    },
    [setVideoSeekTime, setCurrentTime],
  );

  const handleTimeUpdate = useCallback(
    (time: number) => {
      setCurrentTime(time);
      setVideoSeekTime(undefined);
    },
    [setCurrentTime, setVideoSeekTime],
  );

  const handleClipClick = useCallback(
    (clip: Clip) => {
      setActiveClipId(clip.id);
      setVideoSeekTime(clip.start_time);
    },
    [setActiveClipId, setVideoSeekTime],
  );

  const handleClipPlay = useCallback(
    (clip: Clip) => {
      setActiveClipId(clip.id);
      setPreviewClip(clip);
    },
    [setActiveClipId, setPreviewClip],
  );

  const handlePreviewEnd = useCallback(() => setPreviewClip(undefined), [setPreviewClip]);

  // ── Clip CRUD ──────────────────────────────────────────────────────────

  const handleClipDelete = useCallback(
    async (clip: Clip) => {
      if (!confirm('Delete this clip?')) return;
      try {
        await apiClient.deleteClip(clip.id);
        setClips((prev) => prev.filter((c) => c.id !== clip.id));
        if (activeClipId === clip.id) setActiveClipId(undefined);
      } catch (err) {
        console.error('Failed to delete clip:', err);
        alert('Failed to delete clip');
      }
    },
    [activeClipId, setClips, setActiveClipId],
  );

  const handleClipSubtitlesToggle = useCallback(
    async (clip: Clip) => {
      try {
        const updated = await apiClient.updateClipSubtitles(clip.id, {
          enabled: !clip.subtitles_enabled,
          style: clip.subtitles_enabled ? undefined : 'hormozi',
        });
        setClips((prev) => prev.map((c) => (c.id === clip.id ? updated : c)));
      } catch (err) {
        console.error('Failed to toggle subtitles:', err);
      }
    },
    [setClips],
  );

  const handleClipModify = useCallback(
    async (clipId: string, startTime: number, endTime: number) => {
      try {
        const updated = await apiClient.updateClip(clipId, {
          start_time: startTime,
          end_time: endTime,
        });
        setClips((prev) => prev.map((c) => (c.id === clipId ? updated : c)));
      } catch (err) {
        console.error('Failed to modify clip:', err);
        alert('Failed to modify clip');
      }
    },
    [setClips],
  );

  const handleClipsReorder = useCallback(
    async (clipOrders: { clip_id: string; order: number }[]) => {
      // Optimistic update
      setClips((prev) => {
        const next = [...prev];
        clipOrders.forEach(({ clip_id, order }) => {
          const c = next.find((x) => x.id === clip_id);
          if (c) c.order = order;
        });
        return next.sort((a, b) => a.order - b.order);
      });

      try {
        await apiClient.reorderClips(projectId, clipOrders);
      } catch (err) {
        console.error('Failed to reorder clips:', err);
        fetchProject();
      }
    },
    [projectId, setClips, fetchProject],
  );

  // ── Auto-clips placeholder ─────────────────────────────────────────────

  const handleGenerateAutoClips = useCallback(() => {
    setIsGeneratingClips(true);
    setTimeout(() => setIsGeneratingClips(false), 500);
  }, [setIsGeneratingClips]);

  // ── Subtitle editing ───────────────────────────────────────────────────

  const handleSubtitleCueClick = useCallback((_cue: SubtitleCue) => {
    // Could open an inline editor or scroll to cue
  }, []);

  const handleSubtitlesUpdated = useCallback(
    (updatedClip: Clip) => {
      setClips((prev) => prev.map((c) => (c.id === updatedClip.id ? updatedClip : c)));
    },
    [setClips],
  );

  const handleSubtitleSeek = useCallback(
    (relativeTime: number) => {
      if (subtitleEditClip) {
        const abs = subtitleEditClip.start_time + relativeTime;
        setVideoSeekTime(abs);
        setCurrentTime(abs);
      }
    },
    [subtitleEditClip, setVideoSeekTime, setCurrentTime],
  );

  const handleClipClickWithSubtitles = useCallback(
    (clip: Clip) => {
      handleClipClick(clip);
      if (clip.subtitles_enabled) setSubtitleEditClipId(clip.id);
    },
    [handleClipClick, setSubtitleEditClipId],
  );

  const handleClipSubtitlesToggleWithEdit = useCallback(
    async (clip: Clip) => {
      await handleClipSubtitlesToggle(clip);
      if (!clip.subtitles_enabled) {
        setSubtitleEditClipId(clip.id);
      } else if (subtitleEditClipId === clip.id) {
        setSubtitleEditClipId(undefined);
      }
    },
    [handleClipSubtitlesToggle, subtitleEditClipId, setSubtitleEditClipId],
  );

  // ── Export ─────────────────────────────────────────────────────────────

  const handleClipExport = useCallback(
    (clip: Clip) => {
      setExportClip(clip);
      setExportModalOpen(true);
    },
    [setExportClip, setExportModalOpen],
  );

  const handleExportAllClips = useCallback(() => {
    setExportClip(undefined);
    setExportModalOpen(true);
  }, [setExportClip, setExportModalOpen]);

  const handleExportComplete = useCallback(() => {
    fetchProject();
  }, [fetchProject]);

  return {
    handleClipsUpdated,
    handleTimestampClick,
    handleTimeUpdate,
    handleClipClick,
    handleClipPlay,
    handlePreviewEnd,
    handleClipDelete,
    handleClipSubtitlesToggle,
    handleClipModify,
    handleClipsReorder,
    handleGenerateAutoClips,
    handleSubtitleCueClick,
    handleSubtitlesUpdated,
    handleSubtitleSeek,
    handleClipClickWithSubtitles,
    handleClipSubtitlesToggleWithEdit,
    handleClipExport,
    handleExportAllClips,
    handleExportComplete,
  };
}
