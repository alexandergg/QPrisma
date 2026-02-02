/**
 * Application constants
 * Centralized magic numbers and configuration values
 */

// ============================================================================
// Timing Constants (in milliseconds)
// ============================================================================

export const TIMING = {
  /** Polling interval for job status */
  JOB_POLL_INTERVAL: 3000,
  /** Maximum polling attempts before timeout */
  MAX_POLL_ATTEMPTS: 300,
  /** Debounce delay for search input */
  SEARCH_DEBOUNCE: 300,
  /** Debounce delay for resize events */
  RESIZE_DEBOUNCE: 100,
  /** Animation duration for transitions */
  ANIMATION_DURATION: 200,
  /** Toast notification display time */
  TOAST_DURATION: 5000,
  /** WebSocket heartbeat interval */
  WS_HEARTBEAT_INTERVAL: 25000,
  /** WebSocket reconnect base delay */
  WS_RECONNECT_BASE_DELAY: 1000,
  /** WebSocket max reconnect delay */
  WS_MAX_RECONNECT_DELAY: 30000,
} as const;

// ============================================================================
// Video Constants
// ============================================================================

export const VIDEO = {
  /** Seek step in seconds for keyboard navigation */
  SEEK_STEP: 5,
  /** Volume change step */
  VOLUME_STEP: 0.1,
  /** Default playback rate */
  DEFAULT_PLAYBACK_RATE: 1.0,
  /** Minimum clip duration in seconds */
  MIN_CLIP_DURATION: 1,
  /** Maximum clip duration in seconds */
  MAX_CLIP_DURATION: 300,
  /** Timeline zoom min level */
  TIMELINE_MIN_ZOOM: 1,
  /** Timeline zoom max level */
  TIMELINE_MAX_ZOOM: 20,
} as const;

// ============================================================================
// Upload Constants
// ============================================================================

export const UPLOAD = {
  /** Maximum file size in bytes (500MB) */
  MAX_FILE_SIZE: 500 * 1024 * 1024,
  /** Allowed MIME types */
  ALLOWED_MIME_TYPES: [
    'video/mp4',
    'video/webm',
    'video/quicktime',
    'video/x-msvideo',
  ] as const,
  /** Allowed file extensions */
  ALLOWED_EXTENSIONS: ['.mp4', '.webm', '.mov', '.avi'] as const,
  /** Chunk size for large uploads (5MB) */
  CHUNK_SIZE: 5 * 1024 * 1024,
} as const;

// ============================================================================
// Processing Presets
// ============================================================================

export const PROCESSING_PRESETS = {
  fast: {
    name: 'Fast',
    description: 'Quick analysis with fewer frames',
    maxFrames: 30,
  },
  balanced: {
    name: 'Balanced',
    description: 'Good balance of speed and quality',
    maxFrames: 100,
  },
  thorough: {
    name: 'Thorough',
    description: 'Deep analysis with more frames',
    maxFrames: 200,
  },
} as const;

// ============================================================================
// Export Platform Specs
// ============================================================================

export const EXPORT_PLATFORMS = {
  tiktok: {
    name: 'TikTok',
    aspectRatio: '9:16',
    maxDuration: 180,
    resolution: '1080x1920',
  },
  youtube_shorts: {
    name: 'YouTube Shorts',
    aspectRatio: '9:16',
    maxDuration: 60,
    resolution: '1080x1920',
  },
  instagram_reels: {
    name: 'Instagram Reels',
    aspectRatio: '9:16',
    maxDuration: 90,
    resolution: '1080x1920',
  },
  youtube: {
    name: 'YouTube',
    aspectRatio: '16:9',
    maxDuration: null,
    resolution: '1920x1080',
  },
  twitter: {
    name: 'Twitter/X',
    aspectRatio: '16:9',
    maxDuration: 140,
    resolution: '1280x720',
  },
} as const;

// ============================================================================
// Subtitle Styles
// ============================================================================

export const SUBTITLE_STYLES = {
  hormozi: {
    name: 'Hormozi',
    description: 'Word-by-word, bold, yellow/white',
  },
  mrbeast: {
    name: 'MrBeast',
    description: 'Large, dramatic, all caps',
  },
  minimal: {
    name: 'Minimal',
    description: 'Small, clean, professional',
  },
  karaoke: {
    name: 'Karaoke',
    description: 'Highlight current word',
  },
  news: {
    name: 'News',
    description: 'Lower third, solid background',
  },
} as const;

// ============================================================================
// UI Constants
// ============================================================================

export const UI = {
  /** Sidebar width in pixels */
  SIDEBAR_WIDTH: 280,
  /** Sidebar collapsed width in pixels */
  SIDEBAR_COLLAPSED_WIDTH: 72,
  /** Header height in pixels */
  HEADER_HEIGHT: 64,
  /** Maximum items in recent list */
  MAX_RECENT_ITEMS: 10,
  /** Items per page in lists */
  DEFAULT_PAGE_SIZE: 20,
  /** Maximum file name display length */
  MAX_FILENAME_LENGTH: 40,
} as const;

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

export const KEYBOARD_SHORTCUTS = {
  playPause: ' ',
  seekForward: 'ArrowRight',
  seekBackward: 'ArrowLeft',
  volumeUp: 'ArrowUp',
  volumeDown: 'ArrowDown',
  mute: 'm',
  fullscreen: 'f',
  escape: 'Escape',
} as const;

// ============================================================================
// Local Storage Keys
// ============================================================================

export const STORAGE_KEYS = {
  authToken: 'auth_token',
  theme: 'theme',
  sidebarCollapsed: 'sidebar_collapsed',
  recentVideos: 'recent_videos',
  editorPreferences: 'editor_preferences',
  chatHistory: 'chat_history',
} as const;

// ============================================================================
// Error Messages
// ============================================================================

export const ERROR_MESSAGES = {
  networkError: 'Network error. Please check your connection.',
  unauthorized: 'Please log in to continue.',
  forbidden: 'You do not have permission to perform this action.',
  notFound: 'The requested resource was not found.',
  serverError: 'Server error. Please try again later.',
  uploadFailed: 'Upload failed. Please try again.',
  processingFailed: 'Processing failed. Please try again.',
  exportFailed: 'Export failed. Please try again.',
  invalidFile: 'Invalid file type. Please upload a supported video format.',
  fileTooLarge: 'File is too large. Maximum size is 500MB.',
} as const;
