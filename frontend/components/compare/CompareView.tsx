'use client';

import React, { memo, useMemo } from 'react';
import Image from 'next/image';
import { Film, Users, Tag, Clock, X, Sparkles } from 'lucide-react';
import { formatTime, formatDate } from '@/lib/utils';

interface CompareVideo {
  id: string;
  name: string;
  thumbnail?: string;
  duration?: number;
  entities?: string[];
  topics?: string[];
  uploadedAt?: string;
}

interface CompareViewProps {
  videos: CompareVideo[];
  onRemoveVideo?: (id: string) => void;
  onSelectVideo?: (id: string) => void;
}

function CompareView({ videos, onRemoveVideo, onSelectVideo }: CompareViewProps) {
  const { shared, unique } = useMemo(() => {
    if (videos.length < 2) return { shared: [] as string[], unique: {} as Record<string, string[]> };

    const entitySets = videos.map((v) => new Set(v.entities ?? []));
    const allEntities = videos.flatMap((v) => v.entities ?? []);
    const entityCounts = new Map<string, number>();
    for (const entity of allEntities) {
      entityCounts.set(entity, (entityCounts.get(entity) ?? 0) + 1);
    }

    const sharedEntities = [...new Set(allEntities)].filter((e) => {
      let count = 0;
      for (const set of entitySets) {
        if (set.has(e)) count++;
      }
      return count >= 2;
    });

    const uniqueMap: Record<string, string[]> = {};
    for (const video of videos) {
      uniqueMap[video.id] = (video.entities ?? []).filter(
        (e) => !sharedEntities.includes(e)
      );
    }

    return { shared: sharedEntities, unique: uniqueMap };
  }, [videos]);

  if (videos.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="w-16 h-16 rounded-[var(--radius-2xl)] bg-[var(--amber-2)] flex items-center justify-center mb-4">
          <Users className="w-8 h-8 text-[var(--amber-8)]" />
        </div>
        <h3 className="text-lg font-semibold text-[var(--foreground)] mb-1">
          Select at least 2 videos
        </h3>
        <p className="text-sm text-[var(--text-secondary)] max-w-sm">
          Choose videos from your library to compare their entities, topics, and
          insights side by side.
        </p>
      </div>
    );
  }

  const colClass =
    videos.length === 2 ? 'grid-cols-2' : 'grid-cols-3';

  return (
    <div className="bg-[var(--background)] space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-[var(--radius-lg)] bg-[var(--amber-2)] flex items-center justify-center">
          <Users className="w-4.5 h-4.5 text-[var(--amber-8)]" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-[var(--foreground)]">
            Comparing {videos.length} videos
          </h2>
          <p className="text-xs text-[var(--text-secondary)]">
            {shared.length} shared entities found
          </p>
        </div>
      </div>

      {/* Video columns */}
      <div className={`grid ${colClass} gap-4`}>
        {videos.map((video) => (
          <div
            key={video.id}
            className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-xl)] shadow-[var(--shadow-md)] overflow-hidden transition-shadow hover:shadow-[var(--shadow-lg)]"
          >
            {/* Thumbnail */}
            <div className="relative aspect-video bg-[var(--surface-elevated)]">
              {video.thumbnail ? (
                <Image
                  src={video.thumbnail}
                  alt={video.name}
                  fill
                  sizes="(max-width: 768px) 100vw, 50vw"
                  className="object-cover"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <Film className="w-10 h-10 text-[var(--text-tertiary)]" />
                </div>
              )}

              {/* Remove button */}
              {onRemoveVideo && (
                <button
                  onClick={() => onRemoveVideo(video.id)}
                  className="absolute top-2 right-2 w-7 h-7 rounded-[var(--radius-md)] bg-[var(--foreground)]/60 hover:bg-[var(--foreground)]/80 text-white flex items-center justify-center transition-colors"
                  aria-label={`Remove ${video.name}`}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Duration */}
              {video.duration != null && (
                <div className="absolute bottom-2 right-2 bg-[var(--foreground)]/70 text-white text-xs font-mono px-2 py-0.5 rounded-[var(--radius-sm)]">
                  {formatTime(video.duration)}
                </div>
              )}
            </div>

            {/* Meta */}
            <div className="p-4 space-y-3">
              <div>
                <h3
                  className="font-semibold text-[var(--foreground)] truncate cursor-pointer hover:text-[var(--amber-9)] transition-colors"
                  onClick={() => onSelectVideo?.(video.id)}
                  title={video.name}
                >
                  {video.name}
                </h3>
                <div className="flex items-center gap-2 mt-1 text-xs text-[var(--text-secondary)]">
                  {video.duration != null && (
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {formatTime(video.duration)}
                    </span>
                  )}
                  {video.uploadedAt && (
                    <>
                      <span>·</span>
                      <span>{formatDate(video.uploadedAt)}</span>
                    </>
                  )}
                </div>
              </div>

              {/* Unique entities */}
              {(unique[video.id]?.length ?? 0) > 0 && (
                <div>
                  <p className="text-xs font-medium text-[var(--text-secondary)] mb-1.5 flex items-center gap-1">
                    <Tag className="w-3 h-3" />
                    Unique entities
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {unique[video.id].slice(0, 8).map((e) => (
                      <span
                        key={e}
                        className="px-2 py-0.5 text-xs rounded-[var(--radius-full)] bg-[var(--blue-2)] text-[var(--blue-8)] border border-[var(--blue-3)]"
                      >
                        {e}
                      </span>
                    ))}
                    {unique[video.id].length > 8 && (
                      <span className="px-2 py-0.5 text-xs rounded-[var(--radius-full)] bg-[var(--surface-elevated)] text-[var(--text-tertiary)]">
                        +{unique[video.id].length - 8}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Topics */}
              {(video.topics?.length ?? 0) > 0 && (
                <div>
                  <p className="text-xs font-medium text-[var(--text-secondary)] mb-1.5">
                    Topics
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {video.topics!.slice(0, 5).map((t) => (
                      <span
                        key={t}
                        className="px-2 py-0.5 text-xs rounded-[var(--radius-full)] bg-[var(--surface-elevated)] text-[var(--text-secondary)]"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Shared entities */}
      {shared.length > 0 && (
        <div className="bg-[var(--amber-2)] border border-[var(--amber-5)] rounded-[var(--radius-xl)] p-5">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="w-4 h-4 text-[var(--amber-8)]" />
            <h3 className="text-sm font-semibold text-[var(--foreground)]">
              Shared Entities ({shared.length})
            </h3>
          </div>
          <p className="text-xs text-[var(--text-secondary)] mb-3">
            These entities appear across multiple videos in your comparison.
          </p>
          <div className="flex flex-wrap gap-2">
            {shared.map((entity) => (
              <span
                key={entity}
                className="px-2.5 py-1 text-xs font-medium rounded-[var(--radius-full)] bg-[var(--sage-2)] text-[var(--sage-8)] border border-[var(--sage-4)]"
              >
                {entity}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(CompareView);
