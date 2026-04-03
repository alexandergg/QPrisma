import useSWR from 'swr';
import { apiClient, type MediaItem } from '@/lib/api';

export function useUserVideos() {
  const { data, error, isLoading } = useSWR<{ media: MediaItem[] }>(
    'user-videos',
    () => apiClient.getMedia(),
    { revalidateOnFocus: false },
  );

  const videos = data?.media ?? [];

  return {
    videos,
    hasVideos: videos.length > 0,
    videoCount: videos.length,
    recentVideos: videos.slice(0, 4),
    isLoading,
    error,
  };
}
