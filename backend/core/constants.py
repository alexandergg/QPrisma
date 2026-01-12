"""
Application Constants

Centralized constants used throughout the application.
"""

# =============================================================================
# Processing Constants
# =============================================================================

# Video Processing
DEFAULT_MAX_FRAMES = 20
DEFAULT_FRAME_INTERVAL_SECONDS = 30
MIN_FRAME_INTERVAL_SECONDS = 1
MAX_FRAME_INTERVAL_SECONDS = 300

# Scene Detection
DEFAULT_SCENE_THRESHOLD = 0.3
MIN_SCENE_DURATION_SECONDS = 2.0
MAX_SCENE_DURATION_SECONDS = 60.0
DEFAULT_KEYFRAMES_PER_SCENE = 3

# Audio Processing
WHISPER_MAX_FILE_SIZE_MB = 25
AUDIO_CHUNK_DURATION_SECONDS = 300  # 5 minutes

# =============================================================================
# API Constants
# =============================================================================

# Pagination
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Search
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100

# Chat
MAX_CHAT_HISTORY_LENGTH = 20
MAX_CONTEXT_SOURCES = 10

# =============================================================================
# File Limits
# =============================================================================

# Upload limits (in bytes)
MAX_VIDEO_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB
MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB

# Supported formats
SUPPORTED_VIDEO_FORMATS = {"mp4", "mov", "avi", "mkv", "webm"}
SUPPORTED_IMAGE_FORMATS = {"jpg", "jpeg", "png", "gif", "webp"}
SUPPORTED_AUDIO_FORMATS = {"mp3", "wav", "m4a", "ogg"}

# =============================================================================
# Cache TTLs (in seconds)
# =============================================================================

CACHE_TTL_SHORT = 60  # 1 minute
CACHE_TTL_MEDIUM = 300  # 5 minutes
CACHE_TTL_LONG = 3600  # 1 hour
CACHE_TTL_VERY_LONG = 86400  # 24 hours

# =============================================================================
# Neo4j Constants
# =============================================================================

# Node Labels
NODE_VIDEO = "Video"
NODE_SCENE = "Scene"
NODE_FRAME = "Frame"
NODE_AUDIO_SEGMENT = "AudioSegment"
NODE_ENTITY = "Entity"
NODE_TOPIC = "Topic"

# Relationship Types
REL_CONTAINS = "CONTAINS"
REL_HAS_TRANSCRIPT = "HAS_TRANSCRIPT"
REL_APPEARS_WITH = "APPEARS_WITH"
REL_RELATES_TO = "RELATES_TO"
