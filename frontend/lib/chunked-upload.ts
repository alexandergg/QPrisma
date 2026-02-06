/**
 * Chunked Upload Service
 * 
 * High-performance file upload for large files (1GB+) using:
 * - Block-based parallel uploads to Azure Blob Storage
 * - Progress tracking per-block and overall
 * - Resumable uploads
 * - Automatic retry with exponential backoff
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// =============================================================================
// Types
// =============================================================================

export interface ChunkedUploadOptions {
  /** Processing preset (e.g., 'balanced', 'quality', 'speed') */
  preset?: string;
  /** Maximum frames to extract */
  maxFrames?: number;
  /** Enable scene detection */
  useSceneDetection?: boolean;
  /** Enable hierarchical summary */
  useHierarchicalSummary?: boolean;
  /** Block size in MB (8-100, default auto-selected based on file size) */
  blockSizeMb?: number;
  /** Maximum concurrent uploads (default: 6) */
  concurrency?: number;
  /** Progress callback */
  onProgress?: (progress: UploadProgress) => void;
  /** Block uploaded callback */
  onBlockUploaded?: (blockIndex: number, totalBlocks: number) => void;
  /** Abort signal for cancellation */
  abortSignal?: AbortSignal;
}

export interface UploadProgress {
  /** Overall progress 0-100 */
  percent: number;
  /** Bytes uploaded so far */
  bytesUploaded: number;
  /** Total file size in bytes */
  totalBytes: number;
  /** Current upload phase */
  phase: 'initializing' | 'uploading' | 'committing' | 'done' | 'error';
  /** Number of blocks uploaded */
  blocksUploaded: number;
  /** Total number of blocks */
  totalBlocks: number;
  /** Estimated time remaining in seconds */
  estimatedSecondsRemaining?: number;
  /** Upload speed in bytes per second */
  speedBytesPerSecond?: number;
}

export interface ChunkedUploadResult {
  success: boolean;
  mediaId?: string;
  blobName?: string;
  jobId?: string;
  error?: string;
}

interface InitUploadResponse {
  upload_id: string;
  media_id: string;
  blob_name: string;
  block_size: number;
  total_blocks: number;
  upload_url: string;
  sas_expiry: string;
  blocks: Array<{ block_id: string; block_index: number }>;
}

interface CommitUploadResponse {
  media_id: string;
  blob_name: string;
  file_size: number;
  job_id: string | null;
  status: string;
  message: string;
}

// =============================================================================
// Helper Functions
// =============================================================================

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

async function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  maxRetries: number = 3,
  baseDelayMs: number = 1000,
): Promise<T> {
  let lastError: Error | null = null;
  
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error as Error;
      if (attempt < maxRetries) {
        const delay = baseDelayMs * Math.pow(2, attempt);
        await sleep(delay);
      }
    }
  }
  
  throw lastError;
}

// =============================================================================
// Adaptive Block Size
// =============================================================================

/**
 * Select optimal block size based on file size.
 * Larger blocks = fewer HTTP requests = better throughput for big files.
 */
function getAdaptiveBlockSizeMb(fileSizeBytes: number): number {
  const GB = 1024 * 1024 * 1024;
  if (fileSizeBytes > 5 * GB) return 64;   // 5GB+: 64MB blocks
  if (fileSizeBytes > 1 * GB) return 32;   // 1-5GB: 32MB blocks
  return 16;                                // <1GB: 16MB blocks
}

// =============================================================================
// Chunked Upload Class
// =============================================================================

export class ChunkedUploader {
  private file: File;
  private options: ChunkedUploadOptions;
  private uploadSession: InitUploadResponse | null = null;
  private uploadedBlockIds: Set<string> = new Set();
  private startTime: number = 0;
  private bytesUploaded: number = 0;

  constructor(file: File, options: ChunkedUploadOptions = {}) {
    this.file = file;
    this.options = {
      preset: 'balanced',
      maxFrames: 150,
      useSceneDetection: true,
      useHierarchicalSummary: true,
      blockSizeMb: options.blockSizeMb ?? getAdaptiveBlockSizeMb(file.size),
      concurrency: 6,
      ...options,
    };
  }

  /**
   * Upload the file using chunked upload
   */
  async upload(): Promise<ChunkedUploadResult> {
    this.startTime = Date.now();

    try {
      // Phase 1: Initialize upload
      this.reportProgress('initializing', 0, 0);
      await this.initializeUpload();

      if (!this.uploadSession) {
        throw new Error('Failed to initialize upload session');
      }

      // Phase 2: Upload blocks in parallel
      await this.uploadBlocks();

      // Phase 3: Commit the upload
      this.reportProgress('committing', this.file.size, this.uploadSession.total_blocks);
      const result = await this.commitUpload();

      this.reportProgress('done', this.file.size, this.uploadSession.total_blocks);

      return {
        success: true,
        mediaId: result.media_id,
        blobName: result.blob_name,
        jobId: result.job_id || undefined,
      };

    } catch (error) {
      const message = error instanceof Error ? error.message : 'Upload failed';
      this.reportProgress('error', this.bytesUploaded, this.uploadedBlockIds.size);
      return {
        success: false,
        error: message,
      };
    }
  }

  /**
   * Initialize the upload session
   */
  private async initializeUpload(): Promise<void> {
    const response = await fetch(`${API_URL}/upload/chunked/init`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        filename: this.file.name,
        file_size: this.file.size,
        content_type: this.file.type || 'video/mp4',
        block_size_mb: this.options.blockSizeMb,
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `Failed to initialize upload: ${response.status}`);
    }

    this.uploadSession = await response.json();
  }

  /**
   * Upload all blocks in parallel with concurrency control
   */
  private async uploadBlocks(): Promise<void> {
    if (!this.uploadSession) throw new Error('Upload not initialized');

    const { blocks, block_size, upload_url, total_blocks } = this.uploadSession;
    const concurrency = this.options.concurrency || 6;

    // Semaphore-style concurrency: process blocks with a pool of workers
    const blockQueue = [...blocks];
    const errors: Error[] = [];

    const worker = async () => {
      while (blockQueue.length > 0) {
        if (this.options.abortSignal?.aborted) {
          throw new Error('Upload cancelled');
        }
        const block = blockQueue.shift();
        if (!block) break;
        await this.uploadBlock(block, block_size, upload_url, total_blocks);
      }
    };

    const workers = Array.from({ length: Math.min(concurrency, blocks.length) }, () =>
      worker().catch(err => { errors.push(err); }),
    );

    await Promise.all(workers);

    if (errors.length > 0) {
      throw errors[0];
    }
  }

  /**
   * Upload a single block
   */
  private async uploadBlock(
    block: { block_id: string; block_index: number },
    blockSize: number,
    uploadUrl: string,
    totalBlocks: number,
  ): Promise<void> {
    const start = block.block_index * blockSize;
    const end = Math.min(start + blockSize, this.file.size);
    const chunk = this.file.slice(start, end);

    // Build the block upload URL
    // Azure Blob Storage Put Block: {url}&comp=block&blockid={base64_block_id}
    const blockUrl = `${uploadUrl}&comp=block&blockid=${encodeURIComponent(block.block_id)}`;

    await retryWithBackoff(async () => {
      const response = await fetch(blockUrl, {
        method: 'PUT',
        headers: {
          'x-ms-blob-type': 'BlockBlob',
          'Content-Type': 'application/octet-stream',
          'Content-Length': chunk.size.toString(),
        },
        body: chunk,
        signal: this.options.abortSignal,
      });

      if (!response.ok) {
        throw new Error(`Failed to upload block ${block.block_index}: ${response.status}`);
      }
    });

    // Track progress
    this.uploadedBlockIds.add(block.block_id);
    this.bytesUploaded += chunk.size;

    // Report progress
    this.reportProgress('uploading', this.bytesUploaded, this.uploadedBlockIds.size);

    // Call block callback
    this.options.onBlockUploaded?.(block.block_index, totalBlocks);
  }

  /**
   * Commit the upload
   */
  private async commitUpload(): Promise<CommitUploadResponse> {
    if (!this.uploadSession) throw new Error('Upload not initialized');

    // Get ordered list of block IDs
    const orderedBlockIds = this.uploadSession.blocks
      .sort((a, b) => a.block_index - b.block_index)
      .map(b => b.block_id);

    const response = await fetch(`${API_URL}/upload/chunked/commit`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        upload_id: this.uploadSession.upload_id,
        media_id: this.uploadSession.media_id,
        blob_name: this.uploadSession.blob_name,
        block_ids: orderedBlockIds,
        preset: this.options.preset,
        max_frames: this.options.maxFrames,
        use_scene_detection: this.options.useSceneDetection,
        use_hierarchical_summary: this.options.useHierarchicalSummary,
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `Failed to commit upload: ${response.status}`);
    }

    return response.json();
  }

  /**
   * Report progress to callback
   */
  private reportProgress(
    phase: UploadProgress['phase'],
    bytesUploaded: number,
    blocksUploaded: number,
  ): void {
    if (!this.options.onProgress) return;

    const totalBlocks = this.uploadSession?.total_blocks || 0;
    const totalBytes = this.file.size;
    const percent = totalBytes > 0 ? Math.round((bytesUploaded / totalBytes) * 100) : 0;

    // Calculate speed and ETA
    const elapsedMs = Date.now() - this.startTime;
    const speedBytesPerSecond = elapsedMs > 0 ? (bytesUploaded / elapsedMs) * 1000 : 0;
    const remainingBytes = totalBytes - bytesUploaded;
    const estimatedSecondsRemaining = speedBytesPerSecond > 0
      ? Math.round(remainingBytes / speedBytesPerSecond)
      : undefined;

    this.options.onProgress({
      percent,
      bytesUploaded,
      totalBytes,
      phase,
      blocksUploaded,
      totalBlocks,
      estimatedSecondsRemaining,
      speedBytesPerSecond,
    });
  }

  /**
   * Cancel the upload
   */
  async cancel(): Promise<void> {
    if (!this.uploadSession) return;

    try {
      await fetch(`${API_URL}/upload/chunked/cancel/${this.uploadSession.media_id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      });
    } catch {
      // Ignore errors during cancellation
    }
  }

  /**
   * Get the media ID (available after initialization)
   */
  getMediaId(): string | null {
    return this.uploadSession?.media_id || null;
  }
}

// =============================================================================
// Convenience Function
// =============================================================================

/**
 * Upload a file using chunked upload
 * 
 * @example
 * ```ts
 * const result = await uploadFileChunked(file, {
 *   preset: 'balanced',
 *   onProgress: (progress) => {
 *     console.log(`${progress.percent}% uploaded`);
 *   },
 * });
 * 
 * if (result.success) {
 *   console.log(`Uploaded: ${result.mediaId}`);
 * }
 * ```
 */
export async function uploadFileChunked(
  file: File,
  options?: ChunkedUploadOptions,
): Promise<ChunkedUploadResult> {
  const uploader = new ChunkedUploader(file, options);
  return uploader.upload();
}

/**
 * Determine if a file should use chunked upload
 * Recommended for files > 100MB
 */
export function shouldUseChunkedUpload(file: File): boolean {
  const CHUNKED_THRESHOLD = 100 * 1024 * 1024; // 100MB
  return file.size > CHUNKED_THRESHOLD;
}
