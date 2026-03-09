/**
 * Tests for additional hooks in hooks/index.ts
 *
 * Covers: useLocalStorage, useInterval, useKeyboardShortcut, useCopyToClipboard
 * (useDebounce, useToggle, usePrevious are covered in hooks.test.ts)
 */

import { renderHook, act } from '@testing-library/react';
import { useLocalStorage, useInterval, useKeyboardShortcut, useCopyToClipboard } from '@/hooks';

// ---------------------------------------------------------------------------
// localStorage mock
// ---------------------------------------------------------------------------
const store: Record<string, string> = {};
const localStorageMock = {
  getItem: jest.fn((key: string) => store[key] ?? null),
  setItem: jest.fn((key: string, value: string) => {
    store[key] = value;
  }),
  removeItem: jest.fn((key: string) => {
    delete store[key];
  }),
  clear: jest.fn(() => {
    for (const key of Object.keys(store)) delete store[key];
  }),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true });

// ---------------------------------------------------------------------------
// useLocalStorage
// ---------------------------------------------------------------------------
describe('useLocalStorage', () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.clearAllMocks();
  });

  it('returns initial value when nothing is stored', () => {
    const { result } = renderHook(() => useLocalStorage('test-key', 'default'));
    expect(result.current[0]).toBe('default');
  });

  it('reads from localStorage on mount', () => {
    store['test-key'] = JSON.stringify('stored-value');
    const { result } = renderHook(() => useLocalStorage('test-key', 'default'));
    expect(result.current[0]).toBe('stored-value');
  });

  it('writes to localStorage when value is set', () => {
    const { result } = renderHook(() => useLocalStorage('write-key', 42));

    act(() => {
      result.current[1](99);
    });

    expect(result.current[0]).toBe(99);
    expect(store['write-key']).toBe(JSON.stringify(99));
  });

  it('accepts updater function', () => {
    const { result } = renderHook(() => useLocalStorage('fn-key', 10));

    act(() => {
      result.current[1]((prev: number) => prev + 5);
    });

    expect(result.current[0]).toBe(15);
  });

  it('handles objects', () => {
    const { result } = renderHook(() =>
      useLocalStorage('obj-key', { name: 'test' }),
    );

    act(() => {
      result.current[1]({ name: 'updated' });
    });

    expect(result.current[0]).toEqual({ name: 'updated' });
    expect(JSON.parse(store['obj-key'])).toEqual({ name: 'updated' });
  });
});

// ---------------------------------------------------------------------------
// useInterval
// ---------------------------------------------------------------------------
describe('useInterval', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  it('calls callback at specified interval', () => {
    const callback = jest.fn();
    renderHook(() => useInterval(callback, 1000));

    expect(callback).not.toHaveBeenCalled();

    act(() => {
      jest.advanceTimersByTime(1000);
    });
    expect(callback).toHaveBeenCalledTimes(1);

    act(() => {
      jest.advanceTimersByTime(2000);
    });
    expect(callback).toHaveBeenCalledTimes(3);
  });

  it('does not fire when delay is null', () => {
    const callback = jest.fn();
    renderHook(() => useInterval(callback, null));

    act(() => {
      jest.advanceTimersByTime(5000);
    });
    expect(callback).not.toHaveBeenCalled();
  });

  it('cleans up interval on unmount', () => {
    const callback = jest.fn();
    const { unmount } = renderHook(() => useInterval(callback, 500));

    act(() => {
      jest.advanceTimersByTime(500);
    });
    expect(callback).toHaveBeenCalledTimes(1);

    unmount();

    act(() => {
      jest.advanceTimersByTime(2000);
    });
    // Should not have been called again
    expect(callback).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// useKeyboardShortcut
// ---------------------------------------------------------------------------
describe('useKeyboardShortcut', () => {
  it('fires callback on matching key', () => {
    const callback = jest.fn();
    renderHook(() => useKeyboardShortcut('a', callback));

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }));
    });

    expect(callback).toHaveBeenCalledTimes(1);
  });

  it('does not fire for non-matching key', () => {
    const callback = jest.fn();
    renderHook(() => useKeyboardShortcut('a', callback));

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b' }));
    });

    expect(callback).not.toHaveBeenCalled();
  });

  it('respects modifier keys', () => {
    const callback = jest.fn();
    renderHook(() =>
      useKeyboardShortcut('s', callback, { ctrl: true }),
    );

    // Without ctrl
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: false }));
    });
    expect(callback).not.toHaveBeenCalled();

    // With ctrl
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true }));
    });
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it('cleans up listener on unmount', () => {
    const callback = jest.fn();
    const { unmount } = renderHook(() => useKeyboardShortcut('x', callback));

    unmount();

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'x' }));
    });
    expect(callback).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// useCopyToClipboard
// ---------------------------------------------------------------------------
describe('useCopyToClipboard', () => {
  const originalClipboard = navigator.clipboard;

  beforeEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: {
        writeText: jest.fn().mockResolvedValue(undefined),
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: originalClipboard,
      writable: true,
      configurable: true,
    });
  });

  it('copies text and sets copied state', async () => {
    const { result } = renderHook(() => useCopyToClipboard());

    expect(result.current[0]).toBe(false);

    await act(async () => {
      await result.current[1]('hello');
    });

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('hello');
    expect(result.current[0]).toBe(true);
  });

  it('resets copied state after timeout', async () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useCopyToClipboard());

    await act(async () => {
      await result.current[1]('text');
    });
    expect(result.current[0]).toBe(true);

    act(() => {
      jest.advanceTimersByTime(2000);
    });
    expect(result.current[0]).toBe(false);

    jest.useRealTimers();
  });
});
