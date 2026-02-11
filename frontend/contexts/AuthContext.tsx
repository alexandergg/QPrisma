'use client';

import React, { createContext, useContext, useState, useEffect } from 'react';
import { apiClient, User } from '@/lib/api';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Check if user is already logged in on mount
  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    let isMounted = true;
    if (token) {
      // Verify token and load user
      apiClient
        .getCurrentUser()
        .then((userData: User) => {
          if (isMounted) {
            setUser(userData);
          }
        })
        .catch(() => {
          // Token invalid or expired
          localStorage.removeItem('auth_token');
          if (isMounted) {
            setUser(null);
          }
        })
        .finally(() => {
          if (isMounted) {
            setLoading(false);
          }
        });
    } else {
      Promise.resolve().then(() => setLoading(false));
    }
    return () => {
      isMounted = false;
    };
  }, []);

  const login = async (email: string, password: string) => {
    try {
      const tokenData = await apiClient.login(email, password);
      localStorage.setItem('auth_token', tokenData.access_token);

      // Get user info
      const userData = await apiClient.getCurrentUser();
      setUser(userData);
    } catch (error) {
      throw error;
    }
  };

  const register = async (email: string, password: string, name: string) => {
    try {
      const tokenData = await apiClient.register(email, password, name);
      localStorage.setItem('auth_token', tokenData.access_token);

      // Get user info
      const userData = await apiClient.getCurrentUser();
      setUser(userData);
    } catch (error) {
      throw error;
    }
  };

  const logout = () => {
    localStorage.removeItem('auth_token');
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        register,
        logout,
        isAuthenticated: !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
