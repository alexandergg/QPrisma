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
  /** Timeline zoom min level */
  TIMELINE_MIN_ZOOM: 1,
  /** Timeline zoom max level */
  TIMELINE_MAX_ZOOM: 20,
} as const;

// ============================================================================
// Upload Constants
// ============================================================================

export const UPLOAD = {
  /** Maximum videos accepted in a single upload action */
  MAX_FILES: 10,
  /** Maximum file size in bytes (10GB) */
  MAX_FILE_SIZE: 10 * 1024 * 1024 * 1024,
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
  invalidFile:'Invalid file type. Please upload a supported video format.',
  fileTooLarge: 'File is too large. Maximum size is 10GB.',
} as const;
