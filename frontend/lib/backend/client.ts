// server-only: never import this from client components
// Holds the user's Clerk session JWT, which must never reach the browser.
// Import it only from server-side code: route handlers and server actions.

import { auth } from "@clerk/nextjs/server";

export const backendBaseUrl =
  process.env.API_BASE_URL ?? "http://localhost:8000";

const DEFAULT_TIMEOUT_MS = 10_000;

export class BackendError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail?: string;

  constructor(message: string, status: number, code?: string, detail?: string) {
    super(message);
    this.name = "BackendError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

interface BackendErrorEnvelope {
  status?: string;
  error?: { code?: string; message?: string; detail?: string; cause?: string };
}

async function toBackendError(res: Response): Promise<BackendError> {
  let code: string | undefined;
  let detail: string | undefined;
  try {
    const body = (await res.json()) as BackendErrorEnvelope;
    if (body?.status === "error" && body?.error) {
      code = body.error.code;
      detail = body.error.message ?? body.error.detail ?? body.error.cause;
    }
  } catch {
    // Non-JSON body: fall back to res.statusText.
  }
  return new BackendError(detail ?? res.statusText, res.status, code, detail);
}

export interface CallBackendInit {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  timeoutMs?: number;
}

export async function callBackend<T>(
  path: string,
  init: CallBackendInit = {}
): Promise<T> {
  const { userId, getToken } = await auth();
  if (!userId) {
    throw new BackendError("unauthenticated", 401);
  }
  const token = await getToken();
  if (!token) {
    throw new BackendError("no session token", 401);
  }

  const { method = "GET", body, timeoutMs = DEFAULT_TIMEOUT_MS } = init;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${backendBaseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
    if (!res.ok) {
      throw await toBackendError(res);
    }
    if (res.status === 204) {
      // The backend's contract returns empty 204 bodies (e.g. DELETE). Avoid
      // res.json() throwing "Unexpected end of JSON input" for these.
      return undefined as T;
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof BackendError) {
      throw err;
    }
    if (err instanceof Error && err.name === "AbortError") {
      throw new BackendError("backend timeout", 504);
    }
    throw new BackendError((err as Error).message, 502);
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Streaming variant of {@link callBackend}: returns the raw `Response` (with a
 * long-lived body stream) instead of parsing JSON. Use for SSE endpoints such
 * as `/v1/chat/message/stream`. The caller is responsible for reading and
 * parsing the event stream. The abort timeout stays armed for the whole call
 * as a safety cap (default 280s).
 */
export async function callBackendStream(
  path: string,
  init: CallBackendInit = {}
): Promise<Response> {
  const { userId, getToken } = await auth();
  if (!userId) {
    throw new BackendError("unauthenticated", 401);
  }
  const token = await getToken();
  if (!token) {
    throw new BackendError("no session token", 401);
  }

  const { method = "GET", body, timeoutMs = 280_000 } = init;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${backendBaseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
    if (!res.ok) {
      clearTimeout(timeout);
      throw await toBackendError(res);
    }
    return res;
  } catch (err) {
    clearTimeout(timeout);
    if (err instanceof BackendError) {
      throw err;
    }
    if (err instanceof Error && err.name === "AbortError") {
      throw new BackendError("backend timeout", 504);
    }
    throw new BackendError((err as Error).message, 502);
  }
}
