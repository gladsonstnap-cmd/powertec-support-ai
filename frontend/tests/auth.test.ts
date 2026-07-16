import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../lib/api";
import {
  ACCESS_TOKEN_KEY,
  REFRESH_TOKEN_KEY,
  USER_KEY,
  clearSession,
  getAccessToken,
  getCurrentUser,
  getRefreshToken,
  isAuthenticated,
  login,
  logout,
  saveSession
} from "../lib/auth";
import { isProtectedPath } from "../lib/routes";
import { sendSimulatorMessage } from "../lib/simulator";

function createStorage() {
  const store = new Map<string, string>();
  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => store.set(key, value)),
    removeItem: vi.fn((key: string) => store.delete(key)),
    clear: vi.fn(() => store.clear())
  };
}

function mockBrowser() {
  const storage = createStorage();
  const location = { href: "", replace: vi.fn((value: string) => { location.href = value; }) };
  vi.stubGlobal("window", { localStorage: storage, location });
  vi.stubGlobal("document", { cookie: "" });
  return { storage, location };
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  mockBrowser();
});

describe("frontend auth", () => {
  it("identifies protected routes that must redirect to login without a token", () => {
    expect(isProtectedPath("/dashboard")).toBe(true);
    expect(isProtectedPath("/tickets")).toBe(true);
    expect(isProtectedPath("/knowledge")).toBe(true);
    expect(isProtectedPath("/dev/message-simulator")).toBe(true);
    expect(isProtectedPath("/login")).toBe(false);
  });

  it("valid login saves tokens and current user", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      access_token: "access-123",
      refresh_token: "refresh-123",
      user_id: "user-1",
      tenant_id: "tenant-1"
    }), { status: 200 })));

    await login({ email: "admin@powertec.local", password: "valid-password" });

    expect(getAccessToken()).toBe("access-123");
    expect(getRefreshToken()).toBe("refresh-123");
    expect(getCurrentUser()).toEqual({ user_id: "user-1", tenant_id: "tenant-1", email: "admin@powertec.local" });
    expect(isAuthenticated()).toBe(true);
  });

  it("invalid login shows an error by rejecting with the backend message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Credenciais invalidas", { status: 401 })));

    await expect(login({ email: "admin@powertec.local", password: "wrong-password" })).rejects.toThrow("Credenciais invalidas");
  });

  it("apiFetch sends Authorization when a token exists", async () => {
    saveSession("access-456", "refresh-456", { user_id: "user-1", tenant_id: "tenant-1", email: "admin@powertec.local" });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/tickets");

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer access-456");
  });

  it("401 clears the session and redirects to login", async () => {
    const { location } = mockBrowser();
    saveSession("access-789", "refresh-789", { user_id: "user-1", tenant_id: "tenant-1", email: "admin@powertec.local" });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Unauthorized", { status: 401 })));

    await expect(apiFetch("/tickets")).rejects.toThrow("Sua sessao expirou. Entre novamente.");

    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
    expect(location.href).toBe("/login");
  });

  it("apiFetch hides raw backend JSON errors behind a friendly message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Internal raw error" }), { status: 500 })));

    await expect(apiFetch("/dashboard/summary")).rejects.toThrow("Nao foi possivel concluir a operacao.");
  });

  it("logout clears tokens and redirects to login", () => {
    const { location } = mockBrowser();
    saveSession("access-logout", "refresh-logout", { user_id: "user-1", tenant_id: "tenant-1", email: "admin@powertec.local" });

    logout();

    expect(window.localStorage.removeItem).toHaveBeenCalledWith(ACCESS_TOKEN_KEY);
    expect(window.localStorage.removeItem).toHaveBeenCalledWith(REFRESH_TOKEN_KEY);
    expect(window.localStorage.removeItem).toHaveBeenCalledWith(USER_KEY);
    expect(location.href).toBe("/login");
  });

  it("simulator without auth does not send a message", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(sendSimulatorMessage("+5594999990001", "teste")).rejects.toThrow("Autenticacao necessaria");

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("simulator authenticated sends the message", async () => {
    saveSession("access-sim", "refresh-sim", { user_id: "user-1", tenant_id: "tenant-1", email: "admin@powertec.local" });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: "conversation-1", messages: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await sendSimulatorMessage("+5594999990001", "teste");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/dev/messaging/simulate");
  });
});
