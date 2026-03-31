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

// MSAL instance reference — set by AuthContext after initialization
let _msalInstance: import('@azure/msal-browser').IPublicClientApplication | null = null;

export function setMsalInstance(instance: import('@azure/msal-browser').IPublicClientApplication) {
  _msalInstance = instance;
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

// Streaming event data types
export interface StreamEventData {
  session_id?: string;
  tool?: string;
  success?: boolean;
  description?: string;
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

async function getAuthHeaders(): Promise<HeadersInit> {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };

  if (_msalInstance) {
    const accounts = _msalInstance.getAllAccounts();
    if (accounts.length > 0) {
      try {
        const { loginRequest } = await import('@/lib/msal-config');
        const response = await _msalInstance.acquireTokenSilent({
          scopes: loginRequest.scopes as string[],
          account: accounts[0],
        });
        headers['Authorization'] = `Bearer ${response.accessToken}`;
      } catch {
        // Token acquisition failed — request will proceed without auth
      }
    }
  }

  return headers;
}

async function getAuthHeadersWithoutContentType(): Promise<HeadersInit> {
  const headers: HeadersInit = {};

  if (_msalInstance) {
    const accounts = _msalInstance.getAllAccounts();
    if (accounts.length > 0) {
      try {
        const { loginRequest } = await import('@/lib/msal-config');
        const response = await _msalInstance.acquireTokenSilent({
          scopes: loginRequest.scopes as string[],
          account: accounts[0],
        });
        headers['Authorization'] = `Bearer ${response.accessToken}`;
      } catch {
        // Token acquisition failed
      }
    }
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

  async getCurrentUser(): Promise<User> {
    const response = await fetch(`${API_URL}/auth/me`, {
      headers: await getAuthHeaders(),
    });
    return handleResponse<User>(response);
  },

  // --------------------------------------------------------------------------
  // Media
  // --------------------------------------------------------------------------

  async getMedia(): Promise<MediaListResponse> {
    const response = await fetch(`${API_URL}/media`, {
      headers: await getAuthHeaders(),
    });
    return handleResponse<MediaListResponse>(response);
  },

  async getMediaById(mediaId: string): Promise<MediaItem> {
    const response = await fetch(`${API_URL}/media/${mediaId}`, {
      headers: await getAuthHeaders(),
    });
    return handleResponse<MediaItem>(response);
  },

  async deleteMedia(mediaId: string): Promise<void> {
    const response = await fetch(`${API_URL}/media/${mediaId}`, {
      method: 'DELETE',
      headers: await getAuthHeaders(),
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
      headers: await getAuthHeadersWithoutContentType(),
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
      headers: await getAuthHeadersWithoutContentType(),
      body: formData,
    });
    return handleResponse<UploadResponse>(response);
  },

  // --------------------------------------------------------------------------
  // Video Structure
  // --------------------------------------------------------------------------

  async getVideoStructure(videoId: string): Promise<VideoStructureResponse> {
    const response = await fetch(`${API_URL}/media/${videoId}/structure`, {
      headers: await getAuthHeaders(),
    });
    return handleResponse<VideoStructureResponse>(response);
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
      headers: await getAuthHeaders(),
      body: JSON.stringify({
        message: query,
        video_id: videoId,
        chat_history: chatHistory,
      }),
    });
    return handleResponse<ChatResponse>(response);
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

    // Diagnostic: log what we're sending to help debug video selection issues
    if (typeof window !== 'undefined') {
      console.log('[chatWithAgentStream] Sending request', {
        videoId,
        messageMetadata,
        sessionId,
        hasVideoIds: !!videoIds?.length,
      });
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
      headers: await getAuthHeaders(),
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
                } else if (toolMessage?.startsWith('Tool args:')) {
                  // Parse "Tool args: tool_name|description"
                  const payload = toolMessage.replace('Tool args:', '').trim();
                  const sepIdx = payload.indexOf('|');
                  const toolName = sepIdx >= 0 ? payload.slice(0, sepIdx) : payload;
                  const description = sepIdx >= 0 ? payload.slice(sepIdx + 1) : '';
                  yield {
                    event: 'tool_args',
                    data: { tool: toolName, description },
                  };
                } else if (toolMessage?.startsWith('Tool completed:')) {
                  // Parse "Tool completed: tool_name|success"
                  const payload = toolMessage.replace('Tool completed:', '').trim();
                  const sepIdx = payload.indexOf('|');
                  const toolName = sepIdx >= 0 ? payload.slice(0, sepIdx) : payload;
                  const successStr = sepIdx >= 0 ? payload.slice(sepIdx + 1) : 'success';
                  yield {
                    event: 'tool_end',
                    data: { tool: toolName, success: successStr === 'success' },
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
    const res = await fetch(url, { headers: await getAuthHeaders() });
    if (!res.ok) throw new Error(`Graph visualization failed: ${res.statusText}`);
    return res.json();
  },

  /**
   * Expand a node's subgraph for progressive lazy-load visualization.
   */
  async expandGraphNode(nodeId: string, hops = 1, maxNodes = 50) {
    const res = await fetch(`${API_URL}/graph/expand-subgraph`, {
      method: 'POST',
      headers: await getAuthHeaders(),
      body: JSON.stringify({ node_id: nodeId, hops, max_nodes: maxNodes }),
    });
    if (!res.ok) throw new Error(`Graph expansion failed: ${res.statusText}`);
    return res.json();
  },
};
