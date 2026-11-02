import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import type { Store } from '@reduxjs/toolkit';
import { loggedOut, tokenRefreshed } from '../features/auth/authSlice';
import type { RefreshResponse } from '../types/api';

export const api = axios.create({ baseURL: '/api', withCredentials: true });

// Auth endpoints never trigger a silent refresh (they are how we get tokens in the first place).
const NO_REFRESH = ['/auth/login/', '/auth/register/', '/auth/refresh/', '/auth/logout/'];

let refreshInFlight: Promise<string> | null = null;

/** One refresh at a time: parallel 401s all wait on the same request (the "lock"). */
export function refreshAccessToken(): Promise<string> {
  refreshInFlight ??= api
    .post<RefreshResponse>('/auth/refresh/')
    .then((res) => res.data.access)
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
}

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean };

export function setupInterceptors(store: Store<{ auth: { accessToken: string | null } }>) {
  api.interceptors.request.use((config) => {
    const token = store.getState().auth.accessToken;
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
  });

  api.interceptors.response.use(undefined, async (error: AxiosError) => {
    const original = error.config as RetriableConfig | undefined;
    const isAuthCall = NO_REFRESH.some((path) => original?.url?.endsWith(path));
    if (error.response?.status !== 401 || !original || original._retried || isAuthCall) {
      throw error;
    }
    original._retried = true;
    try {
      const access = await refreshAccessToken();
      store.dispatch(tokenRefreshed(access));
    } catch {
      store.dispatch(loggedOut());
      throw error;
    }
    return api(original);
  });
}

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as Record<string, unknown> | undefined;
    if (data) {
      if (typeof data.detail === 'string') return data.detail;
      const first = Object.values(data)[0];
      if (Array.isArray(first) && typeof first[0] === 'string') return first[0];
    }
    if (!error.response) return 'Cannot reach the server.';
  }
  return 'Something went wrong.';
}
