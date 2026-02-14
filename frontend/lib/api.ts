/**
 * QPrisma API Client
 * Centralized API client with TypeScript types for the frontend
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ============================================================================
// Types
// ============================================================================

export interface User {
  id: string;
  email: string;
  full_name?: string;
  created_at?: string;
}

export interface TokenData {
  access_token: string;
  token_type: string;
}

export interface MediaItem {
  id: string;
  original_filename: string;
  filename?: string;
  name?: string;
  media_type?: string;
  file_size?: number;
  uploaded_at?: string;
  processed?: boolean;
  processing_status?: string;
  duration?: number;
  frames_analyzed?: number;
  blob_url?: string;
  audio_data?: {
    transcription?: {
      text: string;
      segments: Array<{
        id: number;
        start: number;
        end: number;
        text: string;
      }>;
    };
  };
}

export interface MediaListResponse {
  media: MediaItem[];
}

export interface UploadResponse {
  media_id: string;
  blob_name: string;
  job_id?: string;
}

export interface Clip {
  id: string;
  project_id: string;
  title?: string;
  start_time: number;
  end_time: number;
  order: number;
  viral_score?: number;
  viral_reasons?: string[];
  is_ai_suggested?: boolean;
  subtitles_enabled?: boolean;
  subtitle_style?: string;
  subtitles_data?: SubtitleData;
  export_status?: 'pending' | 'processing' | 'done' | 'error';
  export_url?: string;
  created_at?: string;
  updated_at?: string;
}

export interface SubtitleData {
  version?: string;
  style: string;
  style_config?: SubtitleStyleConfig;
  clip_duration: number;
  text: string;
  word_count: number;
  cues: SubtitleCue[];
  words: SubtitleWord[];
}

export interface SubtitleStyleConfig {
  css?: {
    fontFamily?: string;
    fontSize?: string;
    fontWeight?: string;
    textTransform?: string;
    color?: string;
    highlightColor?: string;
    activeColor?: string;
    backgroundColor?: string;
    textShadow?: string;
    padding?: string;
    borderRadius?: string;
  };
  animation?: {
    type?: string;
    duration?: number;
  };
}

export interface SubtitleCue {
  id: number;
  start: number;
  end: number;
  text: string;
  words: SubtitleWord[];
}

export interface SubtitleWord {
  word: string;
  start: number;
  end: number;
  edited?: boolean;
  estimated?: boolean;
}

export interface SubtitleStyle {
  id: string;
  name: string;
  description: string;
}

export interface EditorProject {
  id: string;
  name: string;
  source_media_id: string;
  status: 'draft' | 'exporting' | 'completed';
  created_at: string;
  updated_at: string;
}

export interface EditorProjectWithClips extends EditorProject {
  clips: Clip[];
  source_media?: {
    id: string;
    filename?: string;
    blob_url?: string;
    duration?: number;
  };
}

export interface ExportPresets {
  platforms: Record<string, PlatformPreset>;
  qualities: Record<string, QualityPreset>;
  crop_modes: CropMode[];
}

export interface PlatformPreset {
  display_name: string;
  resolution: string;
  aspect_ratio: string;
  max_duration?: number;
}

export interface QualityPreset {
  description: string;
  bitrate?: string;
}

export interface CropMode {
  id: string;
  name: string;
  description: string;
}

export interface ExportEstimate {
  estimated_size_mb: number;
  output_resolution: string;
  estimated_duration_seconds?: number;
}

export interface ExportResult {
  success: boolean;
  clip_id: string;
  output_url?: string;
  error?: string;
}

export interface VideoStructureResponse {
  structure?: {
    scenes?: Array<{
      scene_id: number;
      start_time: number;
      end_time: number;
      duration?: number;
      title?: string;
      summary?: string;
      detected_objects?: string[];
      transcript_segment?: string;
    }>;
    chapters?: Array<{
      chapter_id: number;
      title: string;
      start_time: number;
      end_time: number;
      duration?: number;
      scene_ids?: number[];
      scene_count?: number;
    }>;
    video_summary?: string;
    video_title?: string;
    key_topics?: string[];
  };
  // Alternative flat structure (for backwards compatibility)
  scenes?: Array<{
    scene_id: number;
    start_time: number;
    end_time: number;
    duration?: number;
    title?: string;
    summary?: string;
    detected_objects?: string[];
    transcript_segment?: string;
  }>;
  chapters?: Array<{
    chapter_id: number;
    title: string;
    start_time: number;
    end_time: number;
    duration?: number;
    scene_ids?: number[];
    scene_count?: number;
  }>;
}

export interface GenerateSubtitlesResult {
  success: boolean;
  subtitle_data?: SubtitleData;
  error?: string;
}

export interface ChatResponse {
  response: string;
  sources?: Array<{
    timestamp: number;
    type?: string;
    description?: string;
    score?: number;
  }>;
}

export interface SearchResult {
  id: string;
  frame_number: number;
  timestamp: number;
  content: string;
  score: number;
  type?: 'visual' | 'audio' | 'entity';
}

export interface SearchResponse {
  results: SearchResult[];
  query_expansion?: string[];
}

// Streaming event data types
export interface StreamEventData {
  session_id?: string;
  tool?: string;
  success?: boolean;
  token?: string;
  sources?: Array<{
    timestamp: number;
    type?: string;
    description?: string;
    score?: number;
  }>;
  response?: string;
  tool_calls_made?: number;
  error?: string;
  clips?: Clip[];
}

// Streaming event types
export interface StreamEvent {
  event: string;
  data: StreamEventData;
}

// ============================================================================
// A2A Protocol Types
// ============================================================================

export interface A2APart {
  text?: string;
  data?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface A2AMessage {
  messageId?: string;
  contextId?: string;
  taskId?: string;
  role: 'ROLE_USER' | 'ROLE_AGENT';
  parts: A2APart[];
  metadata?: Record<string, unknown>;
}

export interface A2ATaskStatus {
  state: string;
  message?: A2AMessage;
  timestamp?: string;
}

export interface A2AArtifact {
  artifactId: string;
  name?: string;
  description?: string;
  parts: A2APart[];
  metadata?: Record<string, unknown>;
}

export interface A2ATask {
  id: string;
  contextId: string;
  status: A2ATaskStatus;
  artifacts?: A2AArtifact[];
  history?: A2AMessage[];
  metadata?: Record<string, unknown>;
}

export interface A2ATaskStatusUpdateEvent {
  taskId: string;
  contextId: string;
  status: A2ATaskStatus;
  metadata?: Record<string, unknown>;
}

export interface A2ATaskArtifactUpdateEvent {
  taskId: string;
  contextId: string;
  artifact: A2AArtifact;
  append?: boolean;
  lastChunk?: boolean;
  metadata?: Record<string, unknown>;
}

export interface A2AStreamResponse {
  task?: A2ATask;
  message?: A2AMessage;
  statusUpdate?: A2ATaskStatusUpdateEvent;
  artifactUpdate?: A2ATaskArtifactUpdateEvent;
}

export interface A2ASendMessageRequest {
  message: A2AMessage;
  configuration?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

// ============================================================================
// Helper Functions
// ============================================================================

function getAuthHeaders(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

function getAuthHeadersWithoutContentType(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  const headers: HeadersInit = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP error ${response.status}`);
  }
  return response.json();
}

// ============================================================================
// API Client
// ============================================================================

export const apiClient = {
  // --------------------------------------------------------------------------
  // Auth
  // --------------------------------------------------------------------------

  async login(email: string, password: string): Promise<TokenData> {
    const response = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    return handleResponse<TokenData>(response);
  },

  async register(email: string, password: string, name?: string): Promise<TokenData> {
    const response = await fetch(`${API_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, name }),
    });
    return handleResponse<TokenData>(response);
  },

  async getCurrentUser(): Promise<User> {
    const response = await fetch(`${API_URL}/auth/me`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<User>(response);
  },

  // --------------------------------------------------------------------------
  // Media
  // --------------------------------------------------------------------------

  async getMedia(): Promise<MediaListResponse> {
    const response = await fetch(`${API_URL}/media`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<MediaListResponse>(response);
  },

  async getMediaById(mediaId: string): Promise<MediaItem> {
    const response = await fetch(`${API_URL}/media/${mediaId}`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<MediaItem>(response);
  },

  async getVideoMetadata(videoId: string): Promise<MediaItem> {
    const response = await fetch(`${API_URL}/media/${videoId}`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<MediaItem>(response);
  },

  async deleteMedia(mediaId: string): Promise<void> {
    const response = await fetch(`${API_URL}/media/${mediaId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Failed to delete media: ${response.status}`);
    }
  },

  async uploadVideo(file: File, preset: string, maxFrames: number): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('preset', preset);
    formData.append('max_frames', maxFrames.toString());

    const response = await fetch(`${API_URL}/upload`, {
      method: 'POST',
      headers: getAuthHeadersWithoutContentType(),
      body: formData,
    });
    return handleResponse<UploadResponse>(response);
  },

  async uploadVideoOptimized(
    file: File,
    options: {
      preset?: string;
      maxFrames?: number;
      useSceneDetection?: boolean;
      useHierarchicalSummary?: boolean;
    }
  ): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    if (options.preset) formData.append('preset', options.preset);
    if (options.maxFrames) formData.append('max_frames', options.maxFrames.toString());
    if (options.useSceneDetection !== undefined) formData.append('use_scene_detection', options.useSceneDetection.toString());
    if (options.useHierarchicalSummary !== undefined) formData.append('use_hierarchical_summary', options.useHierarchicalSummary.toString());

    const response = await fetch(`${API_URL}/upload/optimized`, {
      method: 'POST',
      headers: getAuthHeadersWithoutContentType(),
      body: formData,
    });
    return handleResponse<UploadResponse>(response);
  },

  // --------------------------------------------------------------------------
  // Video Structure
  // --------------------------------------------------------------------------

  async getVideoStructure(videoId: string): Promise<VideoStructureResponse> {
    const response = await fetch(`${API_URL}/media/${videoId}/structure`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<VideoStructureResponse>(response);
  },

  async reprocessWithOptimizedPipeline(
    videoId: string,
    options: { useSceneDetection: boolean; useHierarchicalSummary: boolean }
  ): Promise<{ job_id: string }> {
    const response = await fetch(`${API_URL}/processing/reprocess/${videoId}`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(options),
    });
    return handleResponse<{ job_id: string }>(response);
  },

  // --------------------------------------------------------------------------
  // Editor Projects
  // --------------------------------------------------------------------------

  async getEditorProjects(): Promise<EditorProject[]> {
    const response = await fetch(`${API_URL}/editor/projects`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<EditorProject[]>(response);
  },

  async getEditorProject(projectId: string): Promise<EditorProjectWithClips> {
    const response = await fetch(`${API_URL}/editor/projects/${projectId}`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<EditorProjectWithClips>(response);
  },

  async createEditorProject(sourceMediaId: string, name: string): Promise<EditorProject> {
    const response = await fetch(`${API_URL}/editor/projects`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ source_media_id: sourceMediaId, name }),
    });
    return handleResponse<EditorProject>(response);
  },

  async deleteEditorProject(projectId: string): Promise<void> {
    const response = await fetch(`${API_URL}/editor/projects/${projectId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Failed to delete project: ${response.status}`);
    }
  },

  // --------------------------------------------------------------------------
  // Clips
  // --------------------------------------------------------------------------

  async updateClip(
    clipId: string,
    updates: { start_time?: number; end_time?: number; title?: string }
  ): Promise<Clip> {
    const response = await fetch(`${API_URL}/editor/clips/${clipId}`, {
      method: 'PATCH',
      headers: getAuthHeaders(),
      body: JSON.stringify(updates),
    });
    return handleResponse<Clip>(response);
  },

  async deleteClip(clipId: string): Promise<void> {
    const response = await fetch(`${API_URL}/editor/clips/${clipId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Failed to delete clip: ${response.status}`);
    }
  },

  async updateClipSubtitles(
    clipId: string,
    options: { enabled?: boolean; style?: string }
  ): Promise<Clip> {
    const response = await fetch(`${API_URL}/editor/clips/${clipId}/subtitles`, {
      method: 'PATCH',
      headers: getAuthHeaders(),
      body: JSON.stringify(options),
    });
    return handleResponse<Clip>(response);
  },

  async reorderClips(
    projectId: string,
    clipOrders: { clip_id: string; order: number }[]
  ): Promise<void> {
    const response = await fetch(`${API_URL}/editor/projects/${projectId}/reorder`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ clip_orders: clipOrders }),
    });
    if (!response.ok) {
      throw new Error(`Failed to reorder clips: ${response.status}`);
    }
  },

  // --------------------------------------------------------------------------
  // Subtitles
  // --------------------------------------------------------------------------

  async getSubtitleStyles(): Promise<SubtitleStyle[]> {
    const response = await fetch(`${API_URL}/editor/subtitle-styles`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<SubtitleStyle[]>(response);
  },

  async generateClipSubtitles(clipId: string, style: string): Promise<GenerateSubtitlesResult> {
    const response = await fetch(`${API_URL}/editor/clips/${clipId}/generate-subtitles`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ style }),
    });
    return handleResponse<GenerateSubtitlesResult>(response);
  },

  async updateSubtitleCue(clipId: string, cueId: number, text: string): Promise<void> {
    const response = await fetch(`${API_URL}/editor/clips/${clipId}/subtitles/cues/${cueId}`, {
      method: 'PATCH',
      headers: getAuthHeaders(),
      body: JSON.stringify({ text }),
    });
    if (!response.ok) {
      throw new Error(`Failed to update cue: ${response.status}`);
    }
  },

  async exportSubtitlesSRT(clipId: string): Promise<string> {
    const response = await fetch(`${API_URL}/editor/clips/${clipId}/subtitles/export/srt`, {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Failed to export SRT: ${response.status}`);
    }
    return response.text();
  },

  // --------------------------------------------------------------------------
  // Export
  // --------------------------------------------------------------------------

  async getExportPresets(): Promise<ExportPresets> {
    const response = await fetch(`${API_URL}/editor/export/presets`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<ExportPresets>(response);
  },

  async estimateExport(
    durationSeconds: number,
    platform: string,
    quality: string
  ): Promise<ExportEstimate> {
    const response = await fetch(
      `${API_URL}/editor/export/estimate?duration=${durationSeconds}&platform=${platform}&quality=${quality}`,
      { headers: getAuthHeaders() }
    );
    return handleResponse<ExportEstimate>(response);
  },

  async exportClip(
    clipId: string,
    platform: string,
    quality: string,
    cropMode?: string,
    burnSubtitles?: boolean
  ): Promise<ExportResult> {
    const response = await fetch(`${API_URL}/editor/clips/${clipId}/export`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        platform,
        quality,
        crop_mode: cropMode,
        burn_subtitles: burnSubtitles,
      }),
    });
    return handleResponse<ExportResult>(response);
  },

  async exportClipsBatch(
    projectId: string,
    clipIds: string[],
    platform: string,
    quality: string,
    cropMode?: string,
    burnSubtitles?: boolean
  ): Promise<{ results: ExportResult[] }> {
    const response = await fetch(`${API_URL}/editor/projects/${projectId}/export-batch`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        clip_ids: clipIds,
        platform,
        quality,
        crop_mode: cropMode,
        burn_subtitles: burnSubtitles,
      }),
    });
    return handleResponse<{ results: ExportResult[] }>(response);
  },

  // --------------------------------------------------------------------------
  // Chat / Agent Streaming
  // --------------------------------------------------------------------------

  async chatWithVideo(
    query: string,
    videoId: string,
    chatHistory: Array<{ role: string; content: string }>
  ): Promise<ChatResponse> {
    const response = await fetch(`${API_URL}/chat`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        message: query,
        video_id: videoId,
        chat_history: chatHistory,
      }),
    });
    return handleResponse<ChatResponse>(response);
  },

  async enhancedSearch(
    query: string,
    options: {
      mediaId?: string;
      topK?: number;
      useReranking?: boolean;
      useQueryExpansion?: boolean;
    }
  ): Promise<SearchResponse> {
    const params = new URLSearchParams();
    params.append('query', query);
    if (options.mediaId) params.append('media_id', options.mediaId);
    if (options.topK) params.append('top_k', options.topK.toString());
    if (options.useReranking !== undefined) params.append('use_reranking', options.useReranking.toString());
    if (options.useQueryExpansion !== undefined) params.append('use_query_expansion', options.useQueryExpansion.toString());

    const response = await fetch(`${API_URL}/search/enhanced?${params.toString()}`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<SearchResponse>(response);
  },

  /**
   * Stream chat with Video Agent via A2A protocol.
   * 
   * Yields A2AStreamResponse objects containing:
   * - task: Initial task object with SUBMITTED status
   * - statusUpdate: Status changes (WORKING, tool usage, COMPLETED/FAILED)
   * - artifactUpdate: Streaming response chunks
   */
  async *chatWithAgentStream(
    message: string,
    videoId: string | null,
    chatHistory: Array<{ role: string; content: string }>,
    sessionId?: string,
    videoIds?: string[],
    signal?: AbortSignal
  ): AsyncGenerator<StreamEvent> {
    // Build A2A message metadata
    const messageMetadata: Record<string, unknown> = {};
    if (videoId) {
      messageMetadata.media_id = videoId;
    }
    if (videoIds && videoIds.length > 0) {
      messageMetadata.media_ids = videoIds;
      // If no single videoId but we have videoIds, use the first as primary
      if (!videoId && videoIds.length > 0) {
        messageMetadata.media_id = videoIds[0];
      }
    }

    const a2aMessage: A2AMessage = {
      contextId: sessionId,
      role: 'ROLE_USER',
      parts: [{ text: message }],
      metadata: Object.keys(messageMetadata).length > 0 ? messageMetadata : undefined,
    };

    // Include chat history in metadata
    const metadata: Record<string, unknown> = {};
    if (chatHistory.length > 0) {
      metadata.chat_history = chatHistory;
    }

    const request: A2ASendMessageRequest = {
      message: a2aMessage,
      metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
    };

    const response = await fetch(`${API_URL}/a2a/message:stream`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(request),
      signal,
    });

    if (!response.ok) {
      throw new Error(`Chat request failed: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let currentContextId: string | undefined;
    let accumulatedContent = '';
    const toolsUsed: string[] = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') {
            return;
          }
          try {
            const a2aResponse = JSON.parse(data) as A2AStreamResponse;
            
            // Convert A2A events to legacy StreamEvent format for backward compatibility
            if (a2aResponse.task) {
              currentContextId = a2aResponse.task.contextId;
              yield {
                event: 'session',
                data: { session_id: currentContextId },
              };
            }
            
            if (a2aResponse.statusUpdate) {
              const status = a2aResponse.statusUpdate.status;
              const state = status.state;
              
              if (state === 'TASK_STATE_WORKING') {
                // Check if this is a tool update
                const toolMessage = status.message?.parts?.[0]?.text;
                if (toolMessage?.startsWith('Using tool:')) {
                  const toolName = toolMessage.replace('Using tool:', '').trim();
                  toolsUsed.push(toolName);
                  yield {
                    event: 'tool_start',
                    data: { tool: toolName },
                  };
                } else {
                  yield {
                    event: 'thinking',
                    data: {},
                  };
                }
              } else if (state === 'TASK_STATE_COMPLETED') {
                const statusText = status.message?.parts
                  ?.map((part) => part.text)
                  .filter((text): text is string => Boolean(text))
                  .join('\n')
                  .trim();

                const completionText = accumulatedContent || statusText || '';
                yield {
                  event: 'done',
                  data: {
                    response: completionText,
                    tool_calls_made: toolsUsed.length,
                  },
                };
              } else if (state === 'TASK_STATE_FAILED') {
                const errorMsg = status.message?.parts?.[0]?.text || 'Unknown error';
                yield {
                  event: 'error',
                  data: { error: errorMsg },
                };
              }
            }
            
            if (a2aResponse.artifactUpdate) {
              const artifact = a2aResponse.artifactUpdate.artifact;
              const textPart = artifact.parts.find(p => p.text);
              
              if (textPart?.text) {
                if (a2aResponse.artifactUpdate.append) {
                  // Streaming token
                  yield {
                    event: 'token',
                    data: { token: textPart.text },
                  };
                  accumulatedContent += textPart.text;
                } else if (a2aResponse.artifactUpdate.lastChunk) {
                  // Final artifact - content is complete
                  accumulatedContent = textPart.text;
                } else {
                  // Snapshot-style artifact updates
                  accumulatedContent = textPart.text;
                }
              }
              
              // Check for sources artifact
              const dataPart = artifact.parts.find(p => p.data);
              if (dataPart?.data && 'sources' in dataPart.data) {
                const sources = dataPart.data.sources as Array<{
                  timestamp: number;
                  type?: string;
                  description?: string;
                  score?: number;
                }>;
                yield {
                  event: 'sources',
                  data: { sources },
                };
              }
            }
          } catch {
            // Ignore parse errors
          }
        }
      }
    }
  },

  /**
   * Stream chat with Editor Agent via A2A protocol.
   */
  async *chatWithEditorAgentStream(
    message: string,
    projectId: string,
    chatHistory: Array<{ role: string; content: string }>,
    sessionId?: string
  ): AsyncGenerator<StreamEvent> {
    // Build A2A message
    const a2aMessage: A2AMessage = {
      contextId: sessionId,
      role: 'ROLE_USER',
      parts: [{ text: message }],
      metadata: { project_id: projectId },
    };

    const metadata: Record<string, unknown> = {};
    if (chatHistory.length > 0) {
      metadata.chat_history = chatHistory;
    }

    const request: A2ASendMessageRequest = {
      message: a2aMessage,
      metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
    };

    const response = await fetch(`${API_URL}/a2a/editor/message:stream`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`Editor chat request failed: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let currentContextId: string | undefined;
    let accumulatedContent = '';
    const toolsUsed: string[] = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') {
            return;
          }
          try {
            const a2aResponse = JSON.parse(data) as A2AStreamResponse;
            
            // Convert A2A events to legacy StreamEvent format
            if (a2aResponse.task) {
              currentContextId = a2aResponse.task.contextId;
              yield {
                event: 'session',
                data: { session_id: currentContextId },
              };
            }
            
            if (a2aResponse.statusUpdate) {
              const status = a2aResponse.statusUpdate.status;
              const state = status.state;
              
              if (state === 'TASK_STATE_WORKING') {
                const toolMessage = status.message?.parts?.[0]?.text;
                if (toolMessage?.startsWith('Using tool:')) {
                  const toolName = toolMessage.replace('Using tool:', '').trim();
                  toolsUsed.push(toolName);
                  yield {
                    event: 'tool_start',
                    data: { tool: toolName },
                  };
                } else {
                  yield {
                    event: 'thinking',
                    data: {},
                  };
                }
              } else if (state === 'TASK_STATE_COMPLETED') {
                yield {
                  event: 'done',
                  data: {
                    response: accumulatedContent,
                    tool_calls_made: toolsUsed.length,
                  },
                };
              } else if (state === 'TASK_STATE_FAILED') {
                const errorMsg = status.message?.parts?.[0]?.text || 'Unknown error';
                yield {
                  event: 'error',
                  data: { error: errorMsg },
                };
              }
            }
            
            if (a2aResponse.artifactUpdate) {
              const artifact = a2aResponse.artifactUpdate.artifact;
              const textPart = artifact.parts.find(p => p.text);
              
              if (textPart?.text) {
                if (a2aResponse.artifactUpdate.append) {
                  yield {
                    event: 'token',
                    data: { token: textPart.text },
                  };
                  accumulatedContent += textPart.text;
                } else if (a2aResponse.artifactUpdate.lastChunk) {
                  accumulatedContent = textPart.text;
                }
              }
              
              // Check for clips update in artifact data
              const dataPart = artifact.parts.find(p => p.data);
              if (dataPart?.data && 'clips' in dataPart.data) {
                yield {
                  event: 'clips_updated',
                  data: { clips: dataPart.data.clips as Clip[] },
                };
              }
            }
          } catch {
            // Ignore parse errors
          }
        }
      }
    }
  },

  // ==========================================================================
  // Knowledge Graph Visualization
  // ==========================================================================

  /**
   * Get the NVL-compatible graph visualization for a video.
   */
  async getVideoVisualization(
    videoId: string,
    options?: { depth?: number; includeEntities?: boolean; maxNodes?: number }
  ) {
    const params = new URLSearchParams();
    if (options?.depth != null) params.set('depth', String(options.depth));
    if (options?.includeEntities != null) params.set('include_entities', String(options.includeEntities));
    if (options?.maxNodes != null) params.set('max_nodes', String(options.maxNodes));
    const qs = params.toString();
    const url = `${API_URL}/graph/video/${videoId}/visualization${qs ? `?${qs}` : ''}`;
    const res = await fetch(url, { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(`Graph visualization failed: ${res.statusText}`);
    return res.json();
  },

  /**
   * Expand a node's subgraph for progressive lazy-load visualization.
   */
  async expandGraphNode(nodeId: string, hops = 1, maxNodes = 50) {
    const res = await fetch(`${API_URL}/graph/expand-subgraph`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ node_id: nodeId, hops, max_nodes: maxNodes }),
    });
    if (!res.ok) throw new Error(`Graph expansion failed: ${res.statusText}`);
    return res.json();
  },

  /**
   * Get Knowledge Graph stats.
   */
  async getGraphStats() {
    const res = await fetch(`${API_URL}/graph/stats`, { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(`Graph stats failed: ${res.statusText}`);
    return res.json();
  },
};
