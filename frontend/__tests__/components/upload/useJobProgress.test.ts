import { act, renderHook, waitFor } from '@testing-library/react';
import { useJobProgress } from '@/components/upload/useJobProgress';
import type { ProcessingStepData } from '@/components/upload/ProcessingStep';
import { ERROR_MESSAGES, TIMING } from '@/lib/constants';

const mutableTiming = TIMING as unknown as { MAX_POLL_ATTEMPTS: number };
const originalMaxPollAttempts = TIMING.MAX_POLL_ATTEMPTS;

const initialSteps: ProcessingStepData[] = [
  { id: 'upload', name: 'Upload', status: 'pending' },
  { id: 'audio', name: 'Audio', status: 'pending' },
  { id: 'frames', name: 'Frames', status: 'pending' },
];

describe('useJobProgress', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    mutableTiming.MAX_POLL_ATTEMPTS = originalMaxPollAttempts;
    jest.useRealTimers();
    jest.restoreAllMocks();
    localStorage.clear();
  });

  it('polls persisted media status and updates progress', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        processing_status: 'running',
        processing_progress: 0.42,
        processing_message: 'Analyzing frames',
        processing_method: 'databricks',
        last_updated: '2026-05-07T19:00:00Z',
        processed: false,
      }),
    });

    const { result } = renderHook(() =>
      useJobProgress('job-1', 'media-1', initialSteps),
    );

    await waitFor(() => expect(result.current.overallProgress).toBe(42));

    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/media/media-1/status',
      { headers: { 'Content-Type': 'application/json' } },
    );
    expect(result.current.steps.some((step) => step.status === 'in_progress')).toBe(true);
    expect(result.current.estimatedTime).toBe('~6 min remaining');
    expect(result.current.processingMessage).toBe('Analyzing frames');
    expect(result.current.processingMethod).toBe('databricks');
    expect(result.current.backendStatus).toBe('running');
  });

  it('marks all steps completed when persisted status completes', async () => {
    const onComplete = jest.fn();
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        processing_status: 'completed',
        processing_progress: 1,
        processing_message: 'Done',
        processed: true,
      }),
    });

    const { result } = renderHook(() =>
      useJobProgress('job-1', 'media-1', initialSteps, onComplete),
    );

    await waitFor(() => expect(result.current.status).toBe('completed'));

    expect(result.current.overallProgress).toBe(100);
    expect(result.current.steps.every((step) => step.status === 'completed')).toBe(true);
    expect(onComplete).toHaveBeenCalledWith('media-1');
  });

  it('marks processing as failed when persisted status fails', async () => {
    const onError = jest.fn();
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        processing_status: 'error',
        processing_progress: 0.55,
        processing_message: 'Frame analysis failed',
        processed: false,
      }),
    });

    const { result } = renderHook(() =>
      useJobProgress('job-1', 'media-1', initialSteps, undefined, onError),
    );

    await waitFor(() => expect(result.current.status).toBe('error'));

    expect(result.current.error).toBe('Frame analysis failed');
    expect(onError).toHaveBeenCalledWith('Frame analysis failed');
  });

  it('surfaces authorization failures from status polling', async () => {
    const onError = jest.fn();
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      status: 403,
    });

    const { result } = renderHook(() =>
      useJobProgress('job-1', 'media-1', initialSteps, undefined, onError),
    );

    await waitFor(() => expect(result.current.status).toBe('error'));

    expect(result.current.error).toBe(ERROR_MESSAGES.forbidden);
    expect(onError).toHaveBeenCalledWith(ERROR_MESSAGES.forbidden);
  });

  it('surfaces repeated network failures from status polling', async () => {
    jest.useFakeTimers();
    const onError = jest.fn();
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    (global.fetch as jest.Mock).mockRejectedValue(new Error('offline'));

    const { result } = renderHook(() =>
      useJobProgress('job-1', 'media-1', initialSteps, undefined, onError),
    );

    await act(async () => {
      jest.advanceTimersByTime(TIMING.JOB_POLL_INTERVAL * 2);
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.status).toBe('error'));

    expect(result.current.error).toBe(ERROR_MESSAGES.networkError);
    expect(onError).toHaveBeenCalledWith(ERROR_MESSAGES.networkError);
    expect(consoleError).toHaveBeenCalledTimes(3);
  });

  it('stops polling after the maximum attempt count', async () => {
    jest.useFakeTimers();
    mutableTiming.MAX_POLL_ATTEMPTS = 1;
    const onError = jest.fn();
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        processing_status: 'processing',
        processing_progress: 10,
        processed: false,
      }),
    });

    const { result } = renderHook(() =>
      useJobProgress('job-1', 'media-1', initialSteps, undefined, onError),
    );

    await waitFor(() => expect(result.current.overallProgress).toBe(10));

    await act(async () => {
      jest.advanceTimersByTime(TIMING.JOB_POLL_INTERVAL);
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.status).toBe('error'));

    expect(result.current.error).toBe(
      'Processing status check timed out. Please refresh to check the latest status.',
    );
    expect(onError).toHaveBeenCalledWith(
      'Processing status check timed out. Please refresh to check the latest status.',
    );
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});
