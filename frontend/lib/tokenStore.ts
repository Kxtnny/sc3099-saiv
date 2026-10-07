/**
 * Token storage strategy (see briefing "State Management & Token Security"):
 * - Access token: kept ONLY in memory (a module-level variable). Never
 *   persisted to localStorage/sessionStorage. Lost on refresh, which is fine
 *   because we transparently re-derive it from the refresh token on load.
 * - Refresh token: the backend in this project returns it as a JSON field
 *   (not an HttpOnly cookie), so the most secure option available to us
 *   client-side is sessionStorage (tab-scoped, cleared when the tab closes).
 *   If your Module 2 teammate later switches to setting an HttpOnly cookie,
 *   delete the sessionStorage calls below entirely — the browser will send
 *   the cookie automatically.
 */

const REFRESH_KEY = 'saiv_refresh_token';

let accessToken: string | null = null;
let currentUser: unknown = null;

export const tokenStore = {
  getAccessToken(): string | null {
    return accessToken;
  },
  setAccessToken(token: string | null) {
    accessToken = token;
  },
  getRefreshToken(): string | null {
    if (typeof window === 'undefined') return null;
    return window.sessionStorage.getItem(REFRESH_KEY);
  },
  setRefreshToken(token: string | null) {
    if (typeof window === 'undefined') return;
    if (token) {
      window.sessionStorage.setItem(REFRESH_KEY, token);
    } else {
      window.sessionStorage.removeItem(REFRESH_KEY);
    }
  },
  setUser(user: unknown) {
    currentUser = user;
  },
  getUser(): unknown {
    return currentUser;
  },
  clear() {
    accessToken = null;
    currentUser = null;
    if (typeof window !== 'undefined') {
      window.sessionStorage.removeItem(REFRESH_KEY);
    }
  },
};
