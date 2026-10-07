import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { API_BASE_URL } from './config';
import { tokenStore } from './tokenStore';

export const api = axios.create({ baseURL: API_BASE_URL });

// Attach the current access token to every request.
api.interceptors.request.use((config) => {
  const token = tokenStore.getAccessToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On 401, try exactly once to refresh the access token and replay the
// original request. Queue concurrent 401s so we don't fire multiple
// refresh calls in parallel.
let refreshPromise: Promise<string | null> | null = null;

// Notified when the backend rejects the refresh token, so the UI can drop
// back to the login screen instead of showing a dashboard where every
// request fails.
const sessionExpiredListeners = new Set<() => void>();

export function onSessionExpired(listener: () => void): () => void {
  sessionExpiredListeners.add(listener);
  return () => {
    sessionExpiredListeners.delete(listener);
  };
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = tokenStore.getRefreshToken();
  if (!refreshToken) return null;

  try {
    const { data } = await axios.post(`${API_BASE_URL}/auth/refresh`, {
      refresh_token: refreshToken,
    });
    tokenStore.setAccessToken(data.access_token);
    if (data.refresh_token) {
      tokenStore.setRefreshToken(data.refresh_token);
    }
    return data.access_token as string;
  } catch (err) {
    // Only a definitive rejection (expired/invalid token, disabled account)
    // ends the session. Network errors, timeouts, rate limits and 5xx keep
    // the refresh token so the user isn't logged out by a flaky connection.
    const status = (err as AxiosError).response?.status;
    const rejected = status !== undefined && status >= 400 && status < 500 && status !== 408 && status !== 429;
    if (rejected) {
      tokenStore.clear();
      sessionExpiredListeners.forEach((listener) => listener());
    }
    return null;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;

    if (error.response?.status === 401 && original && !original._retried) {
      original._retried = true;

      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null;
        });
      }
      const newToken = await refreshPromise;

      if (newToken) {
        original.headers = original.headers ?? {};
        original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      }
    }

    if (error.response?.status === 429) {
      const retryAfter = error.response.headers['retry-after'];
      (error as AxiosError & { retryAfter?: string }).retryAfter = retryAfter;
    }

    return Promise.reject(error);
  }
);

export { refreshAccessToken };
