import { clearSession, getAccessToken } from "@/lib/auth";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const DEFAULT_TIMEOUT_MS = 20000;

export async function apiFetch(path: string, options: RequestInit = {}) {
  const token = getAccessToken();
  const headers = new Headers(options.headers);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
      signal: options.signal ?? controller.signal
    });
  } catch (exc) {
    if (exc instanceof DOMException && exc.name === "AbortError") {
      throw new Error("Tempo limite ao acessar o servidor. Tente novamente.");
    }
    throw new Error("Nao foi possivel acessar o servidor. Tente novamente.");
  } finally {
    clearTimeout(timeout);
  }

  if (response.status === 401) {
    clearSession();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Sua sessao expirou. Entre novamente.");
  }

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text ? "Nao foi possivel concluir a operacao." : `Erro HTTP ${response.status}`);
  }

  return response;
}

export async function apiJson<T>(path: string, options: RequestInit = {}) {
  const response = await apiFetch(path, options);
  return response.json() as Promise<T>;
}
