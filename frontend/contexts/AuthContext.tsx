'use client';

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import {
  PublicClientApplication,
  InteractionRequiredAuthError,
} from '@azure/msal-browser';
import { MsalProvider, useMsal, useIsAuthenticated } from '@azure/msal-react';
import { msalConfig, loginRequest } from '@/lib/msal-config';
import { apiClient, setMsalInstance, type User } from '@/lib/api';

// Singleton MSAL instance — created once at module scope
const msalInstance = new PublicClientApplication(msalConfig);

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: () => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function AuthProviderInner({ children }: { children: React.ReactNode }) {
  const { instance, accounts } = useMsal();
  const isMsalAuthenticated = useIsAuthenticated();
  const [user, setUser] = useState<User | null>(null);
  const [userFetched, setUserFetched] = useState(false);

  // Derive loading: true only while actively fetching the user profile
  const loading = isMsalAuthenticated && accounts.length > 0 && !userFetched;

  // Load user profile from backend when MSAL has an active account
  useEffect(() => {
    let isMounted = true;

    if (isMsalAuthenticated && accounts.length > 0) {
      // Tell api.ts about the MSAL instance so it can acquire tokens
      setMsalInstance(instance);

      apiClient
        .getCurrentUser()
        .then((userData: User) => {
          if (isMounted) setUser(userData);
        })
        .catch(() => {
          if (isMounted) setUser(null);
        })
        .finally(() => {
          if (isMounted) setUserFetched(true);
        });
    }

    return () => {
      isMounted = false;
    };
  }, [isMsalAuthenticated, accounts, instance]);

  const login = useCallback(async () => {
    try {
      await instance.loginPopup(loginRequest);
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        await instance.loginRedirect(loginRequest);
      } else {
        throw err;
      }
    }
  }, [instance]);

  const logout = useCallback(() => {
    setUser(null);
    instance.logoutPopup({
      postLogoutRedirectUri: msalConfig.auth.postLogoutRedirectUri as string,
    });
  }, [instance]);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
        isAuthenticated: !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  // In MSAL popup flow the popup must still load MsalProvider so that
  // handleRedirectPromise() runs — it processes the auth code and
  // broadcasts the result back to the parent window via BroadcastChannel.
  // We only skip AuthProviderInner (user profile fetch, auth context) in
  // the popup since it isn't needed there.
  const [isPopup] = useState(
    () => typeof window !== 'undefined' && !!window.opener
  );

  if (isPopup) {
    return (
      <MsalProvider instance={msalInstance}>
        {children}
      </MsalProvider>
    );
  }

  return (
    <MsalProvider instance={msalInstance}>
      <AuthProviderInner>{children}</AuthProviderInner>
    </MsalProvider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
