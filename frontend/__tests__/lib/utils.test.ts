import { formatTime, formatTimeWithMs, formatFileSize, formatFileSizeMB, formatDate, formatDuration, generateId, clamp } from '@/lib/utils';

describe('formatTime', () => {
  it('formats seconds to MM:SS', () => {
    expect(formatTime(0)).toBe('0:00');
    expect(formatTime(65)).toBe('1:05');
    expect(formatTime(125)).toBe('2:05');
  });

  it('formats hours correctly', () => {
    expect(formatTime(3661)).toBe('1:01:01');
    expect(formatTime(7325)).toBe('2:02:05');
  });

  it('handles NaN and undefined', () => {
    expect(formatTime(NaN)).toBe('0:00');
    expect(formatTime(undefined as unknown as number)).toBe('0:00');
  });
});

describe('formatTimeWithMs', () => {
  it('formats with milliseconds', () => {
    expect(formatTimeWithMs(0)).toBe('0:00.00');
    expect(formatTimeWithMs(65.5)).toBe('1:05.50');
    expect(formatTimeWithMs(125.25)).toBe('2:05.25');
  });
});

describe('formatFileSize', () => {
  it('formats bytes to human readable', () => {
    expect(formatFileSize(0)).toBe('0 Bytes');
    expect(formatFileSize(1024)).toBe('1 KB');
    expect(formatFileSize(1048576)).toBe('1 MB');
    expect(formatFileSize(1073741824)).toBe('1 GB');
  });

  it('handles undefined', () => {
    expect(formatFileSize(undefined)).toBe('0 Bytes');
  });
});

describe('formatFileSizeMB', () => {
  it('formats megabytes', () => {
    expect(formatFileSizeMB(100)).toBe('100.0 MB');
    expect(formatFileSizeMB(1500)).toBe('1.5 GB');
  });
});

describe('formatDate', () => {
  it('formats date strings', () => {
    const result = formatDate('2024-01-15');
    expect(result).toMatch(/Jan 15, 2024/);
  });

  it('formats Date objects', () => {
    const result = formatDate(new Date('2024-06-20'));
    expect(result).toMatch(/Jun 20, 2024/);
  });

  it('handles undefined', () => {
    expect(formatDate(undefined)).toBe('Unknown date');
  });

  it('handles invalid dates', () => {
    expect(formatDate('invalid')).toBe('Unknown date');
  });
});

describe('formatDuration', () => {
  it('formats short durations', () => {
    expect(formatDuration(30)).toBe('30s');
    expect(formatDuration(90)).toBe('1m 30s');
    expect(formatDuration(3660)).toBe('1h 1m');
  });

  it('handles edge cases', () => {
    expect(formatDuration(0)).toBe('0s');
    expect(formatDuration(NaN)).toBe('0s');
  });
});

describe('generateId', () => {
  it('generates unique IDs', () => {
    const id1 = generateId();
    const id2 = generateId();
    expect(id1).not.toBe(id2);
    expect(id1.length).toBe(7);
  });
});

describe('clamp', () => {
  it('clamps values within range', () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-5, 0, 10)).toBe(0);
    expect(clamp(15, 0, 10)).toBe(10);
  });
});
