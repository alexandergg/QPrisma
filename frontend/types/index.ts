/**
 * Shared TypeScript types for the QPrisma frontend
 * 
 * These types are used across multiple components and pages.
 * Component-specific types should remain in their respective files.
 */

// ============================================================================
// Video & Media Types
// ============================================================================

export interface Scene {
  scene_id: number;
  start_time: number;
  end_time: number;
  duration?: number;
  title?: string;
  summary?: string;
  detected_objects?: string[];
  transcript_segment?: string;
}

export interface Chapter {
  chapter_id: number;
  title: string;
  start_time: number;
  end_time: number;
  duration?: number;
  scene_ids?: number[];
  scene_count?: number;
  themes?: string[];
  summary?: string;
}

export interface VideoStructure {
  scenes?: Scene[];
  chapters?: Chapter[];
  video_summary?: string;
  video_title?: string;
  key_topics?: string[];
}

export interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  text: string;
}

export interface AudioData {
  transcription?: {
    text: string;
    segments: TranscriptSegment[];
  };
}

// ============================================================================
// Chat Types
// ============================================================================

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  frames?: Frame[];
  isLoading?: boolean;
  sources?: ChatSource[];
  toolCalls?: number;
}

export interface ChatSource {
  timestamp: number;
  type: 'visual' | 'audio' | 'entity';
  description?: string;
  score?: number;
}

export interface Frame {
  id: string;
  frame_number: number;
  timestamp: number;
  content: string;
  score: number;
  type?: 'visual' | 'audio' | 'entity';
  transcript_text?: string;
  visual_description?: string;
  detected_objects?: string[];
}

// ============================================================================
// Processing Types
// ============================================================================

export type ProcessingStatus = 
  | 'pending'
  | 'uploading'
  | 'processing'
  | 'completed'
  | 'error'
  | 'cancelled';

export interface ProcessingJob {
  id: string;
  mediaId: string;
  status: ProcessingStatus;
  progress: number;
  stage?: string;
  message?: string;
  error?: string;
  startedAt?: Date;
  completedAt?: Date;
}

// ============================================================================
// UI State Types
// ============================================================================

export interface SelectOption<T = string> {
  value: T;
  label: string;
  description?: string;
  disabled?: boolean;
}

export interface TabItem {
  id: string;
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  badge?: number | string;
  disabled?: boolean;
}

export interface MenuItem {
  id: string;
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  onClick?: () => void;
  href?: string;
  variant?: 'default' | 'danger';
  disabled?: boolean;
}

// ============================================================================
// Form Types
// ============================================================================

export interface FieldError {
  field: string;
  message: string;
}

export interface FormState<T> {
  values: T;
  errors: FieldError[];
  isSubmitting: boolean;
  isValid: boolean;
}

// ============================================================================
// Pagination Types
// ============================================================================

export interface PaginationParams {
  page: number;
  limit: number;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
  totalPages: number;
}

// ============================================================================
// WebSocket Types
// ============================================================================

export type WebSocketStatus = 
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'error';

export interface WebSocketMessage<T = unknown> {
  type: string;
  payload: T;
  timestamp?: string;
}

// ============================================================================
// Knowledge Graph Visualization Types
// ============================================================================

export type GraphNodeType =
  | 'Video'
  | 'Chapter'
  | 'Scene'
  | 'Frame'
  | 'Entity'
  | 'AudioSegment'
  | 'Topic';

export type GraphEntityType =
  | 'person'
  | 'object'
  | 'location'
  | 'action'
  | 'concept'
  | 'text'
  | 'brand'
  | 'event';

export interface GraphNode {
  id: string;
  caption: string;
  color: string;
  size: number;
  icon?: string;
  node_type: GraphNodeType;
  entity_type?: GraphEntityType;
  properties: Record<string, unknown>;
}

export interface GraphRelationship {
  id: string;
  from: string;
  to: string;
  caption: string;
  type: string;
  color: string;
  properties: Record<string, unknown>;
}

export interface GraphVisualizationData {
  video_id: string;
  nodes: GraphNode[];
  relationships: GraphRelationship[];
  total_nodes: number;
  total_relationships: number;
  depth: number;
}

export interface GraphExpandResult {
  center_node_id: string;
  nodes: GraphNode[];
  relationships: GraphRelationship[];
  total_nodes: number;
  total_relationships: number;
}
