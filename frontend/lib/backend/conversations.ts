// server-only: never import this from client components.
// Typed, envelope-free helpers for the backend /v1/conversations API
// (Postgres-backed chat history). Import them only from server code (BFF
// route handlers); they rely on callBackend, which holds the Clerk JWT and
// must never reach the browser.

import { BackendError, callBackend } from "@/lib/backend/client";

/** Summary row returned by `GET /v1/conversations` (camelCase, newest first). */
export interface BackendConversationSummary {
  id: string;
  title: string;
  messageCount: number;
  updatedAt: string | null;
  preview: string;
  pinned: boolean;
  folder: string;
}

/** Message returned inside `GET /v1/conversations/{id}`. */
export interface BackendConversationMessage {
  id: string;
  role: string;
  content: string;
  parts: Record<string, unknown> | null;
  createdAt: string | null;
}

/** Full conversation returned by `GET /v1/conversations/{id}`. */
export interface BackendConversation {
  id: string;
  title: string;
  status: string;
  createdAt: string | null;
  updatedAt: string | null;
  messages: BackendConversationMessage[];
}

/**
 * List conversations for the authenticated tenant/user.
 *
 * The backend returns a bare JSON array (not a UnifiedResponse envelope) so
 * `Array.isArray()` can be used directly.
 */
export async function listConversations(): Promise<
  BackendConversationSummary[]
> {
  const res = await callBackend<BackendConversationSummary[]>(
    "/v1/conversations",
    { timeoutMs: 60_000 }
  );
  return Array.isArray(res) ? res : [];
}

/**
 * Fetch one full conversation (with messages). Returns `null` on 404 — the
 * backend deliberately does not distinguish "missing" from "forbidden", and
 * the BFF maps both to its own not_found response.
 */
export async function getConversation(
  id: string
): Promise<BackendConversation | null> {
  try {
    return await callBackend<BackendConversation>(`/v1/conversations/${id}`, {
      timeoutMs: 60_000,
    });
  } catch (err) {
    if (err instanceof BackendError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

export interface DeleteConversationResult {
  /** true when the backend actually tombstoned the conversation row. */
  deleted: boolean;
}

/**
 * Delete one conversation. The backend tombstones it (204), or 404s when the
 * row is missing, already deleted, or not deletable by the caller.
 *
 * CD-3 honest 404: a 404 is a REAL failure result (`deleted: false`), never a
 * swallowed success — the BFF turns it into `{success:false, deleted:false}`
 * and the sidebar keeps the row instead of hiding it.
 */
export async function deleteConversation(
  id: string
): Promise<DeleteConversationResult> {
  try {
    await callBackend<void>(`/v1/conversations/${id}`, {
      method: "DELETE",
      timeoutMs: 60_000,
    });
    return { deleted: true };
  } catch (err) {
    if (err instanceof BackendError && err.status === 404) {
      return { deleted: false };
    }
    throw err;
  }
}

/** Delete every conversation the caller may delete; returns the count. */
export async function deleteAllConversations(): Promise<number> {
  const res = await callBackend<{ deleted?: number }>("/v1/conversations", {
    method: "DELETE",
    timeoutMs: 60_000,
  });
  return typeof res?.deleted === "number" ? res.deleted : 0;
}

export interface PatchConversationTitleResult {
  /** false when the conversation does not exist (deleted) — never created. */
  ok: boolean;
}

/**
 * Rename an existing conversation (CD-2). Maps to the backend PATCH
 * /v1/conversations/{id} — title-only and NEVER creates a row — replacing the
 * old POST saveConversation, which could resurrect a deleted chat. A 404 here
 * means the chat was deleted (or never existed): returned as `{ok:false}` so
 * the BFF logs it without re-creating anything.
 */
export async function patchConversationTitle(
  id: string,
  title: string
): Promise<PatchConversationTitleResult> {
  try {
    await callBackend<{ conversation_id: string }>(`/v1/conversations/${id}`, {
      method: "PATCH",
      body: { title },
      timeoutMs: 60_000,
    });
    return { ok: true };
  } catch (err) {
    if (err instanceof BackendError && err.status === 404) {
      return { ok: false };
    }
    throw err;
  }
}

/** BFF DELETE envelope (CD-3): success only when the backend really deleted. */
export interface DeleteChatResponse {
  success: boolean;
  deleted: boolean;
}

/** Build the BFF DELETE envelope from the backend deletion result (CD-3). */
export function buildDeleteChatResponse(deleted: boolean): DeleteChatResponse {
  return { success: deleted, deleted };
}
