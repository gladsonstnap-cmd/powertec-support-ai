export const ACCESS_TOKEN_KEY = "powertec_access_token";
export const REFRESH_TOKEN_KEY = "powertec_refresh_token";
export const USER_KEY = "powertec_user";
export const DEFAULT_TENANT_SLUG = "powertec";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export type AuthUser = {
  user_id: string;
  tenant_id: string;
  email: string;
  tenant_name?: string;
};

export type LoginInput = {
  email: string;
  password: string;
  tenantSlug?: string;
};

type LoginResponse = {
  access_token: string;
  refresh_token: string;
  user_id: string;
  tenant_id: string;
};

function hasBrowserStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function setDevCookie(name: string, value: string) {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; SameSite=Lax`;
}

function clearDevCookie(name: string) {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; path=/; max-age=0; SameSite=Lax`;
}

export function saveSession(accessToken: string, refreshToken: string, user: AuthUser) {
  if (!hasBrowserStorage()) return;
  window.localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  window.localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  setDevCookie(ACCESS_TOKEN_KEY, accessToken);
}

export function getAccessToken() {
  if (!hasBrowserStorage()) return null;
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken() {
  if (!hasBrowserStorage()) return null;
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function getCurrentUser(): AuthUser | null {
  if (!hasBrowserStorage()) return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function isAuthenticated() {
  return Boolean(getAccessToken());
}

export function clearSession() {
  if (hasBrowserStorage()) {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY);
    window.localStorage.removeItem(REFRESH_TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  }
  clearDevCookie(ACCESS_TOKEN_KEY);
}

export function logout() {
  clearSession();
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
}

export async function login({ email, password, tenantSlug = DEFAULT_TENANT_SLUG }: LoginInput) {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_slug: tenantSlug,
      email,
      password
    })
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "E-mail ou senha invalidos.");
  }

  const data = (await response.json()) as LoginResponse;
  const user = { user_id: data.user_id, tenant_id: data.tenant_id, email };
  saveSession(data.access_token, data.refresh_token, user);
  return user;
}
