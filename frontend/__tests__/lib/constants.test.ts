import { TIMING, VIDEO, UPLOAD, UI, STORAGE_KEYS, ERROR_MESSAGES } from '@/lib/constants';

describe('Constants', () => {
  describe('TIMING', () => {
    it('has valid polling interval', () => {
      expect(TIMING.JOB_POLL_INTERVAL).toBeGreaterThan(0);
      expect(TIMING.JOB_POLL_INTERVAL).toBeLessThan(60000);
    });

    it('has valid debounce delays', () => {
      expect(TIMING.SEARCH_DEBOUNCE).toBeGreaterThanOrEqual(100);
      expect(TIMING.SEARCH_DEBOUNCE).toBeLessThanOrEqual(1000);
    });
  });

  describe('VIDEO', () => {
    it('has valid seek step', () => {
      expect(VIDEO.SEEK_STEP).toBeGreaterThan(0);
      expect(VIDEO.SEEK_STEP).toBeLessThanOrEqual(30);
    });

    it('has valid zoom limits', () => {
      expect(VIDEO.TIMELINE_MIN_ZOOM).toBeLessThan(VIDEO.TIMELINE_MAX_ZOOM);
    });
  });

  describe('UPLOAD', () => {
    it('has valid max file size', () => {
      expect(UPLOAD.MAX_FILE_SIZE).toBeGreaterThan(0);
      // 10GB for chunked video uploads
      expect(UPLOAD.MAX_FILE_SIZE).toBe(10 * 1024 * 1024 * 1024);
    });

    it('has valid MIME types', () => {
      expect(UPLOAD.ALLOWED_MIME_TYPES).toContain('video/mp4');
      expect(UPLOAD.ALLOWED_MIME_TYPES.length).toBeGreaterThan(0);
    });
  });

  describe('UI', () => {
    it('has valid sidebar widths', () => {
      expect(UI.SIDEBAR_WIDTH).toBeGreaterThan(UI.SIDEBAR_COLLAPSED_WIDTH);
    });
  });

  describe('STORAGE_KEYS', () => {
    it('has auth token key', () => {
      expect(STORAGE_KEYS.authToken).toBe('auth_token');
    });
  });

  describe('ERROR_MESSAGES', () => {
    it('has network error message', () => {
      expect(ERROR_MESSAGES.networkError).toBeTruthy();
    });

    it('has all required error messages', () => {
      expect(ERROR_MESSAGES.unauthorized).toBeTruthy();
      expect(ERROR_MESSAGES.serverError).toBeTruthy();
      expect(ERROR_MESSAGES.uploadFailed).toBeTruthy();
    });
  });
});
