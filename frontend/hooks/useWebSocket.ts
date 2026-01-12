/**
 * useWebSocket Hook para QPrisma
 * Gestiona conexiones WebSocket para actualizaciones en tiempo real.
 *
 * Características:
 * - Reconexión automática con backoff exponencial
 * - Heartbeat para mantener conexión viva
 * - Tipado TypeScript completo
 * - Callbacks para diferentes tipos de eventos
 *
 * Uso:
 *   const { status, progress, error, isConnected } = useJobWebSocket(jobId, {
 *     onProgress: (data) => console.log('Progress:', data.progress),
 *     onCompleted: (result) => console.log('Done!', result),
 *     onError: (err) => console.error('Error:', err),
 *   });
 */

import { useState, useEffect, useCallback, useRef } from 'react';

// =============================================================================
// Types
// =============================================================================

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

export interface JobProgress {
  progress: number;
  stage: string;
  message?: string;
  status?: string;
}

export interface WebSocketMessage {
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
  job_id?: string;
}

export interface UseJobWebSocketOptions {
  /** Callback cuando hay actualización de progreso */
  onProgress?: (data: JobProgress) => void;
  /** Callback cuando el job se completa */
  onCompleted?: (result: Record<string, unknown>) => void;
  /** Callback cuando el job falla */
  onError?: (error: string) => void;
  /** Callback cuando se conecta */
  onConnected?: () => void;
  /** Callback cuando se desconecta */
  onDisconnected?: () => void;
  /** Auto-reconectar (default: true) */
  autoReconnect?: boolean;
  /** Intervalo máximo de reconexión en ms (default: 30000) */
  maxReconnectInterval?: number;
  /** URL base del WebSocket (default: auto-detecta) */
  wsUrl?: string;
}

export interface UseJobWebSocketReturn {
  /** Estado actual del WebSocket */
  status: WebSocketStatus;
  /** Progreso actual del job (0-100) */
  progress: number;
  /** Stage actual del procesamiento */
  stage: string;
  /** Mensaje de estado */
  message: string | null;
  /** Error si ocurrió */
  error: string | null;
  /** Si está conectado */
  isConnected: boolean;
  /** Resultado del job (cuando completa) */
  result: Record<string, unknown> | null;
  /** Función para reconectar manualmente */
  reconnect: () => void;
  /** Función para desconectar */
  disconnect: () => void;
  /** Función para suscribirse a otro job */
  subscribe: (jobId: string) => void;
}

// =============================================================================
// Helper Functions
// =============================================================================

function getWebSocketUrl(jobId: string, baseUrl?: string): string {
  if (baseUrl) {
    return `${baseUrl}/ws/jobs/${jobId}`;
  }

  // Auto-detectar URL basándose en la ubicación actual
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = process.env.NEXT_PUBLIC_API_URL
    ? new URL(process.env.NEXT_PUBLIC_API_URL).host
    : window.location.host;

  return `${protocol}//${host}/ws/jobs/${jobId}`;
}

// =============================================================================
// Main Hook
// =============================================================================

export function useJobWebSocket(
  jobId: string | null,
  options: UseJobWebSocketOptions = {}
): UseJobWebSocketReturn {
  const {
    onProgress,
    onCompleted,
    onError,
    onConnected,
    onDisconnected,
    autoReconnect = true,
    maxReconnectInterval = 30000,
    wsUrl,
  } = options;

  // State
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttempts = useRef(0);
  const heartbeatIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Cleanup function
  const cleanup = useCallback(() => {
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = null;
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  // Connect function
  const connect = useCallback(() => {
    if (!jobId) return;

    cleanup();
    setStatus('connecting');
    setError(null);

    const url = getWebSocketUrl(jobId, wsUrl);
    console.log(`[WebSocket] Connecting to ${url}`);

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[WebSocket] Connected');
        setStatus('connected');
        reconnectAttempts.current = 0;
        onConnected?.();

        // Iniciar heartbeat (ping cada 25 segundos)
        heartbeatIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 25000);
      };

      ws.onmessage = (event) => {
        try {
          const data: WebSocketMessage = JSON.parse(event.data);
          console.log('[WebSocket] Message:', data.type, data.payload);

          switch (data.type) {
            case 'connected':
              // Confirmación de conexión
              break;

            case 'job_progress':
              const progressData = data.payload as unknown as JobProgress;
              setProgress(progressData.progress || 0);
              setStage(progressData.stage || '');
              setMessage(progressData.message || null);
              onProgress?.(progressData);
              break;

            case 'job_completed':
              setProgress(100);
              setStage('completed');
              setMessage('Procesamiento completado');
              const resultData = data.payload.result as Record<string, unknown>;
              setResult(resultData);
              onCompleted?.(resultData);
              break;

            case 'job_failed':
              const errorMsg = (data.payload.error as string) || 'Error desconocido';
              setError(errorMsg);
              setStage('failed');
              onError?.(errorMsg);
              break;

            case 'heartbeat':
            case 'pong':
              // Heartbeat recibido, conexión OK
              break;

            default:
              console.log('[WebSocket] Unknown message type:', data.type);
          }
        } catch (e) {
          console.error('[WebSocket] Failed to parse message:', e);
        }
      };

      ws.onerror = (event) => {
        console.error('[WebSocket] Error:', event);
        setStatus('error');
      };

      ws.onclose = (event) => {
        console.log('[WebSocket] Closed:', event.code, event.reason);
        setStatus('disconnected');
        onDisconnected?.();

        // Auto-reconectar si está habilitado y no fue un cierre limpio
        if (autoReconnect && event.code !== 1000) {
          const delay = Math.min(
            1000 * Math.pow(2, reconnectAttempts.current),
            maxReconnectInterval
          );
          console.log(`[WebSocket] Reconnecting in ${delay}ms...`);
          reconnectAttempts.current++;

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        }
      };
    } catch (e) {
      console.error('[WebSocket] Failed to create connection:', e);
      setStatus('error');
      setError(e instanceof Error ? e.message : 'Error de conexión');
    }
  }, [jobId, wsUrl, autoReconnect, maxReconnectInterval, onConnected, onDisconnected, onProgress, onCompleted, onError, cleanup]);

  // Disconnect function
  const disconnect = useCallback(() => {
    cleanup();
    setStatus('disconnected');
  }, [cleanup]);

  // Reconnect function
  const reconnect = useCallback(() => {
    reconnectAttempts.current = 0;
    connect();
  }, [connect]);

  // Subscribe to another job
  const subscribe = useCallback((newJobId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'subscribe',
        payload: { job_id: newJobId }
      }));
    }
  }, []);

  // Effect: Connect when jobId changes
  useEffect(() => {
    if (jobId) {
      connect();
    } else {
      disconnect();
    }

    return () => {
      cleanup();
    };
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    status,
    progress,
    stage,
    message,
    error,
    isConnected: status === 'connected',
    result,
    reconnect,
    disconnect,
    subscribe,
  };
}

// =============================================================================
// Simple Hook (sin callbacks, solo state)
// =============================================================================

export function useJobProgress(jobId: string | null) {
  return useJobWebSocket(jobId);
}

// =============================================================================
// Hook para múltiples jobs
// =============================================================================

export interface MultiJobProgress {
  [jobId: string]: JobProgress & { status: WebSocketStatus };
}

export function useMultiJobWebSocket(
  jobIds: string[],
  options: Omit<UseJobWebSocketOptions, 'onProgress' | 'onCompleted' | 'onError'> & {
    onJobProgress?: (jobId: string, data: JobProgress) => void;
    onJobCompleted?: (jobId: string, result: Record<string, unknown>) => void;
    onJobError?: (jobId: string, error: string) => void;
  } = {}
) {
  const [jobs, setJobs] = useState<MultiJobProgress>({});

  // Crear un WebSocket por cada job
  // Nota: En producción, sería mejor usar un solo WebSocket y suscribirse a múltiples jobs
  useEffect(() => {
    const connections: WebSocket[] = [];

    jobIds.forEach((jobId) => {
      if (!jobId) return;

      const url = getWebSocketUrl(jobId, options.wsUrl);
      const ws = new WebSocket(url);

      ws.onopen = () => {
        setJobs((prev) => ({
          ...prev,
          [jobId]: { ...prev[jobId], status: 'connected' } as JobProgress & { status: WebSocketStatus },
        }));
      };

      ws.onmessage = (event) => {
        try {
          const data: WebSocketMessage = JSON.parse(event.data);

          if (data.type === 'job_progress') {
            const progressData = data.payload as unknown as JobProgress;
            setJobs((prev) => ({
              ...prev,
              [jobId]: { ...progressData, status: 'connected' },
            }));
            options.onJobProgress?.(jobId, progressData);
          } else if (data.type === 'job_completed') {
            setJobs((prev) => ({
              ...prev,
              [jobId]: { progress: 100, stage: 'completed', status: 'connected' },
            }));
            options.onJobCompleted?.(jobId, data.payload.result as Record<string, unknown>);
          } else if (data.type === 'job_failed') {
            setJobs((prev) => ({
              ...prev,
              [jobId]: { progress: 0, stage: 'failed', status: 'error' },
            }));
            options.onJobError?.(jobId, data.payload.error as string);
          }
        } catch (e) {
          console.error('[WebSocket] Parse error:', e);
        }
      };

      ws.onclose = () => {
        setJobs((prev) => ({
          ...prev,
          [jobId]: { ...prev[jobId], status: 'disconnected' } as JobProgress & { status: WebSocketStatus },
        }));
      };

      connections.push(ws);
    });

    return () => {
      connections.forEach((ws) => ws.close());
    };
  }, [jobIds.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  return jobs;
}

export default useJobWebSocket;
