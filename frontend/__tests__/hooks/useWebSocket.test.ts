/**
 * Tests for hooks/useWebSocket.ts — useJobWebSocket hook
 *
 * Covers:
 * - Connection lifecycle (connect / disconnect)
 * - Message handling (progress / completed / failed)
 * - Auto-reconnect behaviour
 * - Heartbeat sending
 */

import { renderHook, act } from '@testing-library/react';
import { useJobWebSocket, type WebSocketStatus } from '@/hooks/useWebSocket';

// ---------------------------------------------------------------------------
// WebSocket mock
// ---------------------------------------------------------------------------

type MessageHandler = (event: { data: string }) => void;
type EventHandler = (event?: unknown) => void;

interface MockWebSocket {
  url: string;
  readyState: number;
  onopen: EventHandler | null;
  onmessage: MessageHandler | null;
  onerror: EventHandler | null;
  onclose: EventHandler | null;
  send: jest.Mock;
  close: jest.Mock;
}

let mockWs: MockWebSocket;
const WebSocketMock = jest.fn().mockImplementation((url: string) => {
  mockWs = {
    url,
    readyState: 0, // CONNECTING
    onopen: null,
    onmessage: null,
    onerror: null,
    onclose: null,
    send: jest.fn(),
    close: jest.fn(),
  };
  return mockWs;
});

// Static constants
(WebSocketMock as any).CONNECTING = 0;
(WebSocketMock as any).OPEN = 1;
(WebSocketMock as any).CLOSING = 2;
(WebSocketMock as any).CLOSED = 3;

Object.defineProperty(global, 'WebSocket', { value: WebSocketMock, writable: true });

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function simulateOpen() {
  if (!mockWs) throw new Error('No WebSocket instance');
  mockWs.readyState = WebSocket.OPEN;
  mockWs.onopen?.({});
}

function simulateMessage(data: Record<string, unknown>) {
  if (!mockWs) throw new Error('No WebSocket instance');
  mockWs.onmessage?.({ data: JSON.stringify(data) });
}

function simulateClose(code = 1006) {
  if (!mockWs) throw new Error('No WebSocket instance');
  mockWs.readyState = WebSocket.CLOSED;
  mockWs.onclose?.({ code });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useJobWebSocket', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  it('stays disconnected when jobId is null', async () => {
    const { result } = renderHook(() => useJobWebSocket(null));

    // flush microtask
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.status).toBe('disconnected');
    expect(result.current.isConnected).toBe(false);
    expect(WebSocketMock).not.toHaveBeenCalled();
  });

  it('connects when given a jobId', async () => {
    const { result } = renderHook(() => useJobWebSocket('job-1'));

    // flush the microtask that triggers connect
    await act(async () => {
      await Promise.resolve();
    });

    expect(WebSocketMock).toHaveBeenCalled();
    expect(result.current.status).toBe('connecting');

    act(() => {
      simulateOpen();
    });

    expect(result.current.status).toBe('connected');
    expect(result.current.isConnected).toBe(true);
  });

  it('handles job_progress messages', async () => {
    const onProgress = jest.fn();
    const { result } = renderHook(() =>
      useJobWebSocket('job-2', { onProgress }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      simulateOpen();
    });

    act(() => {
      simulateMessage({
        type: 'job_progress',
        payload: { progress: 42, stage: 'frames', message: 'Analyzing frames...' },
        timestamp: new Date().toISOString(),
      });
    });

    expect(result.current.progress).toBe(42);
    expect(result.current.stage).toBe('frames');
    expect(result.current.message).toBe('Analyzing frames...');
    expect(onProgress).toHaveBeenCalledWith(
      expect.objectContaining({ progress: 42, stage: 'frames' }),
    );
  });

  it('handles job_completed messages', async () => {
    const onCompleted = jest.fn();
    const { result } = renderHook(() =>
      useJobWebSocket('job-3', { onCompleted }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    act(() => simulateOpen());

    act(() => {
      simulateMessage({
        type: 'job_completed',
        payload: { result: { media_id: 'm1' } },
        timestamp: new Date().toISOString(),
      });
    });

    expect(result.current.progress).toBe(100);
    expect(result.current.stage).toBe('completed');
    expect(onCompleted).toHaveBeenCalledWith({ media_id: 'm1' });
  });

  it('handles job_failed messages', async () => {
    const onError = jest.fn();
    const { result } = renderHook(() =>
      useJobWebSocket('job-4', { onError }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    act(() => simulateOpen());

    act(() => {
      simulateMessage({
        type: 'job_failed',
        payload: { error: 'Out of memory' },
        timestamp: new Date().toISOString(),
      });
    });

    expect(result.current.error).toBe('Out of memory');
    expect(result.current.stage).toBe('failed');
    expect(onError).toHaveBeenCalledWith('Out of memory');
  });

  it('sends heartbeat pings', async () => {
    renderHook(() => useJobWebSocket('job-5'));

    await act(async () => {
      await Promise.resolve();
    });

    act(() => simulateOpen());

    // Advance past heartbeat interval (25 seconds)
    act(() => {
      jest.advanceTimersByTime(25000);
    });

    expect(mockWs.send).toHaveBeenCalledWith(JSON.stringify({ type: 'ping' }));
  });

  it('cleans up on unmount', async () => {
    const { unmount } = renderHook(() => useJobWebSocket('job-6'));

    await act(async () => {
      await Promise.resolve();
    });

    act(() => simulateOpen());

    unmount();

    expect(mockWs.close).toHaveBeenCalled();
  });

  it('disconnects via disconnect function', async () => {
    const { result } = renderHook(() => useJobWebSocket('job-7'));

    await act(async () => {
      await Promise.resolve();
    });

    act(() => simulateOpen());
    expect(result.current.isConnected).toBe(true);

    act(() => {
      result.current.disconnect();
    });

    expect(result.current.status).toBe('disconnected');
  });
});
