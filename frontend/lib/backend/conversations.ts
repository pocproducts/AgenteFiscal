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
    return await callBackend<BackendConversation>(
      `/v1/conversations/${id}`,
      { timeoutMs: 60_000 }
    );
  } catch (err) {
    if (err instanceof BackendError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

/** Hard-delete one conversation. Backend returns 204 with an empty body. */
export async function deleteConversation(id: string): Promise<void> {
  await callBackend<void>(`/v1/conversations/${id}`, {
    method: "DELETE",
    timeoutMs: 60_000,
  });
}

/** Delete every conversation the caller may delete; returns the count. */
export async function deleteAllConversations(): Promise<number> {
  const res = await callBackend<{ deleted?: number }>("/v1/conversations", {
    method: "DELETE",
    timeoutMs: 60_000,
  });
  return typeof res?.deleted === "number" ? res.deleted : 0;
}

export interface SaveConversationInput {
  id: string;
  title?: string;
  messages?: Array<{ role: string; content: string }>;
  profileId?: string | null;
}

/**
 * Upsert a conversation. Used by the BFF only where it owns real data (e.g.
 * updating the final chat title); message persistence itself is done by the
 * backend inside /v1/chat/message{,/stream} — the BFF must NOT write messages
 * through this to avoid duplicating what the backend already stored.
 */
export async function saveConversation(
  input: SaveConversationInput
): Promise<void> {
  await callBackend<{ conversation_id: string }>("/v1/conversations", {
    method: "POST",
    body: {
      id: input.id,
      ...(input.title !== undefined ? { title: input.title } : {}),
      ...(input.messages !== undefined ? { messages: input.messages } : {}),
      ...(input.profileId ? { profile_id: input.profileId } : {}),
    },
    timeoutMs: 60_000,
  });
}