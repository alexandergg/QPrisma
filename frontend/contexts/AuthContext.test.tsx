/**
 * Tests for contexts/AuthContext.tsx
 *
 * Covers:
 * - useAuth throws when used outside provider
 * - Renders children and provides default state
 * - Login flow (sets user and stores token)
 * - Logout flow (clears user and removes token)
 */

import React from 'react';
import { render, screen, act, waitFor } from '@testing-library/react';
import { AuthProvider, useAuth } from './AuthContext';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockFetch = jest.fn();
global.fetch = mockFetch;

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

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    headers: new Headers(),
  } as unknown as Response;
}

// Consumer component to access the context
function AuthConsumer() {
  const { user, loading, isAuthenticated, login, logout } = useAuth();

  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="authenticated">{String(isAuthenticated)}</span>
      <span data-testid="user">{user ? user.email : 'none'}</span>
      <button onClick={() => login('test@test.com', 'pass')}>Login</button>
      <button onClick={logout}>Logout</button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AuthContext', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.clear();
  });

  it('throws when useAuth is used outside AuthProvider', () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => {
      render(<AuthConsumer />);
    }).toThrow('useAuth must be used within an AuthProvider');

    spy.mockRestore();
  });

  it('provides unauthenticated state initially when no token', async () => {
    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });

    expect(screen.getByTestId('authenticated').textContent).toBe('false');
    expect(screen.getByTestId('user').textContent).toBe('none');
  });

  it('verifies existing token on mount', async () => {
    localStorageMock.setItem('auth_token', 'existing-token');
    store['auth_token'] = 'existing-token';

    mockFetch.mockResolvedValueOnce(
      jsonResponse({ id: '1', email: 'saved@test.com' }),
    );

    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });

    expect(screen.getByTestId('authenticated').textContent).toBe('true');
    expect(screen.getByTestId('user').textContent).toBe('saved@test.com');
  });

  it('clears invalid token on mount', async () => {
    localStorageMock.setItem('auth_token', 'bad-token');
    store['auth_token'] = 'bad-token';

    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: 'Invalid' }, 401),
    );

    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });

    expect(screen.getByTestId('authenticated').textContent).toBe('false');
    expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
  });

  it('login stores token and loads user', async () => {
    // login response
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ access_token: 'new-tok', token_type: 'bearer' }),
    );
    // getCurrentUser response
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ id: '2', email: 'new@test.com' }),
    );

    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });

    await act(async () => {
      screen.getByText('Login').click();
    });

    await waitFor(() => {
      expect(screen.getByTestId('user').textContent).toBe('new@test.com');
    });

    expect(localStorageMock.setItem).toHaveBeenCalledWith('auth_token', 'new-tok');
  });

  it('logout clears token and user', async () => {
    localStorageMock.setItem('auth_token', 'tok');
    store['auth_token'] = 'tok';

    mockFetch.mockResolvedValueOnce(
      jsonResponse({ id: '1', email: 'u@t.com' }),
    );

    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated').textContent).toBe('true');
    });

    act(() => {
      screen.getByText('Logout').click();
    });

    expect(screen.getByTestId('authenticated').textContent).toBe('false');
    expect(screen.getByTestId('user').textContent).toBe('none');
    expect(localStorageMock.removeItem).toHaveBeenCalledWith('auth_token');
  });
});
