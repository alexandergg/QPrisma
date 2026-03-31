/**
 * Tests for contexts/AuthContext.tsx (MSAL-based auth)
 *
 * Covers:
 * - useAuth throws when used outside provider
 * - Renders unauthenticated state when no MSAL account
 * - Loads user profile when MSAL account is present
 * - Login triggers MSAL loginPopup
 * - Logout clears user and calls MSAL logoutPopup
 */

import React from 'react';
import { render, screen, act, waitFor } from '@testing-library/react';

// ---------------------------------------------------------------------------
// Mock MSAL before importing AuthContext
// ---------------------------------------------------------------------------

const mockLoginPopup = jest.fn();
const mockLogoutPopup = jest.fn();
const mockAcquireTokenSilent = jest.fn();
const mockGetAllAccounts = jest.fn().mockReturnValue([]);

jest.mock('@azure/msal-browser', () => {
  return {
    PublicClientApplication: jest.fn().mockImplementation(() => ({
      loginPopup: mockLoginPopup,
      logoutPopup: mockLogoutPopup,
      acquireTokenSilent: mockAcquireTokenSilent,
      getAllAccounts: mockGetAllAccounts,
      getActiveAccount: jest.fn().mockReturnValue(null),
      setActiveAccount: jest.fn(),
      initialize: jest.fn().mockResolvedValue(undefined),
    })),
    InteractionRequiredAuthError: class extends Error {
      constructor(msg: string) {
        super(msg);
        this.name = 'InteractionRequiredAuthError';
      }
    },
    LogLevel: { Warning: 2 },
  };
});

const mockUseMsal = jest.fn();
const mockUseIsAuthenticated = jest.fn();

jest.mock('@azure/msal-react', () => ({
  MsalProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useMsal: () => mockUseMsal(),
  useIsAuthenticated: () => mockUseIsAuthenticated(),
}));

jest.mock('@/lib/msal-config', () => ({
  msalConfig: { auth: { postLogoutRedirectUri: 'http://localhost:3000' } },
  loginRequest: { scopes: ['api://test/access_as_user'] },
}));

// Mock api module
const mockGetCurrentUser = jest.fn();
jest.mock('@/lib/api', () => ({
  apiClient: { getCurrentUser: (...args: unknown[]) => mockGetCurrentUser(...args) },
  setMsalInstance: jest.fn(),
}));

import { AuthProvider, useAuth } from './AuthContext';

// Consumer component to access the context
function AuthConsumer() {
  const { user, loading, isAuthenticated, login, logout } = useAuth();

  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="authenticated">{String(isAuthenticated)}</span>
      <span data-testid="user">{user ? user.email : 'none'}</span>
      <button onClick={() => login()}>Login</button>
      <button onClick={logout}>Logout</button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AuthContext (MSAL)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseMsal.mockReturnValue({
      instance: {
        loginPopup: mockLoginPopup,
        logoutPopup: mockLogoutPopup,
        acquireTokenSilent: mockAcquireTokenSilent,
        getAllAccounts: mockGetAllAccounts,
      },
      accounts: [],
    });
    mockUseIsAuthenticated.mockReturnValue(false);
  });

  it('throws when useAuth is used outside AuthProvider', () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => {
      render(<AuthConsumer />);
    }).toThrow('useAuth must be used within an AuthProvider');

    spy.mockRestore();
  });

  it('provides unauthenticated state when no MSAL account', async () => {
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

  it('loads user profile when MSAL account is present', async () => {
    mockUseMsal.mockReturnValue({
      instance: {
        loginPopup: mockLoginPopup,
        logoutPopup: mockLogoutPopup,
        acquireTokenSilent: mockAcquireTokenSilent,
        getAllAccounts: mockGetAllAccounts,
      },
      accounts: [{ username: 'user@example.com' }],
    });
    mockUseIsAuthenticated.mockReturnValue(true);
    mockGetCurrentUser.mockResolvedValueOnce({ id: '1', email: 'user@example.com' });

    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });

    expect(screen.getByTestId('authenticated').textContent).toBe('true');
    expect(screen.getByTestId('user').textContent).toBe('user@example.com');
  });

  it('login triggers MSAL loginPopup', async () => {
    mockLoginPopup.mockResolvedValue({});

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

    expect(mockLoginPopup).toHaveBeenCalled();
  });

  it('logout clears user and calls MSAL logoutPopup', async () => {
    mockUseMsal.mockReturnValue({
      instance: {
        loginPopup: mockLoginPopup,
        logoutPopup: mockLogoutPopup,
        acquireTokenSilent: mockAcquireTokenSilent,
        getAllAccounts: mockGetAllAccounts,
      },
      accounts: [{ username: 'user@example.com' }],
    });
    mockUseIsAuthenticated.mockReturnValue(true);
    mockGetCurrentUser.mockResolvedValueOnce({ id: '1', email: 'user@example.com' });

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

    expect(mockLogoutPopup).toHaveBeenCalled();
    expect(screen.getByTestId('user').textContent).toBe('none');
  });
});
