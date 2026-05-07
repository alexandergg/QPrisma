export function videoChatHref(videoId: string): string {
  return `/chat?videoId=${encodeURIComponent(videoId)}`;
}

