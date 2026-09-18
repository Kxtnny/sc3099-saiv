'use client';

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api, refreshAccessToken } from './api';
import { tokenStore } from './tokenStore';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'student' | 'ta' | 'instructor' | 'admin';
  camera_consent?: boolean;
  geolocation_consent?: boolean;
  face_enrolled?: boolean;
}

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => void;
  updateConsent: (patch: { camera_consent?: boolean; geolocation_consent?: boolean }) => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    const { data } = await api.get<User>('/users/me');
    setUser(data);
    tokenStore.setUser(data);
  }, []);

  // On mount: the access token lives only in memory, so after a page
  // refresh we re-derive it from the refresh token (sessionStorage) if any.
  useEffect(() => {
    (async () => {
      const token = await refreshAccessToken();
      if (token) {
        try {
          await refreshUser();
        } catch {
          tokenStore.clear();
        }
      }
      setLoading(false);
    })();
  }, [refreshUser]);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await api.post('/auth/login', { email, password });
    tokenStore.setAccessToken(data.access_token);
    tokenStore.setRefreshToken(data.refresh_token);
    setUser(data.user);
    tokenStore.setUser(data.user);
  }, []);

  const register = useCallback(async (email: string, password: string, fullName: string) => {
    await api.post('/auth/register', {
      email,
      password,
      full_name: fullName,
      role: 'student',
    });
    // Registration doesn't return tokens per the spec — log in right after.
    await login(email, password);
  }, [login]);

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  const updateConsent = useCallback(async (patch: { camera_consent?: boolean; geolocation_consent?: boolean }) => {
    const { data } = await api.put('/users/me', patch);
    setUser(data);
    tokenStore.setUser(data);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, updateConsent, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
