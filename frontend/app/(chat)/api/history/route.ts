import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import {
  deleteAllConversations,
  listConversations,
  type BackendConversationSummary,
} from "@/lib/backend/conversations";
import { BackendError } from "@/lib/backend/client";
import { ChatbotError, type ErrorCode } from "@/lib/errors";
import type { Chat } from "@/lib/db/schema";

// ── Real backend history BFF ────────────────────────────────────────────────
// Consumes GET/DELETE /v1/conversations (Postgres) with the user's Clerk JWT
// via the server-only client. The ephemeral in-memory mock is gone.

type ChatHistory = { chats: Chat[]; hasMore: boolean };

// Backend summaries are camelCase and newest-first. Map into the Chat shape the
// sidebar groups/renders: grouping uses createdAt (driven by updatedAt so a
// just-updated chat groups today), the spinner uses status.
function toChat(summary: BackendConversationSummary): Chat {
  return {
    id: summary.id,
    title: summary.title || "Nueva conversación",
    createdAt: summary.updatedAt ? new Date(summary.updatedAt) : new Date(0),
    userId: "",
    tenantId: "",
    visibility: "private",
    status: "done",
  };
}

// Cursor pagination over the newest-first list. Names follow the OpenAI-style
// convention used by the sidebar pagination key: starting_after returns items
// newer than the cursor, ending_before returns items older than it.
function applyPagination(
  summaries: BackendConversationSummary[],
  limit: number,
  startingAfter: string | null,
  endingBefore: string | null
): ChatHistory {
  let ordered = summaries;

  if (startingAfter) {
    const idx = ordered.findIndex((s) => s.id === startingAfter);
    if (idx === -1) {
      return { chats: [], hasMore: false };
    }
    ordered = ordered.slice(0, idx);
  } else if (endingBefore) {
    const idx = ordered.findIndex((s) => s.id === endingBefore);
    if (idx === -1) {
      return { chats: [], hasMore: false };
    }
    ordered = ordered.slice(idx + 1);
  }

  const hasMore = ordered.length > limit;
  return { chats: ordered.slice(0, limit).map(toChat), hasMore };
}

function backendErrorToCode(err: unknown): ErrorCode {
  if (err instanceof BackendError) {
    if (err.status === 401 || err.status === 403) {
      return "unauthorized:history";
    }
    if (err.status === 404) {
      return "not_found:history";
    }
    if (err.status >= 400 && err.status < 500) {
      return "bad_request:history";
    }
    return "offline:history";
  }
  return "offline:history";
}

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;

  const limit = Math.min(
    Math.max(Number.parseInt(searchParams.get("limit") || "10", 10), 1),
    50
  );
  const startingAfter = searchParams.get("starting_after");
  const endingBefore = searchParams.get("ending_before");

  if (startingAfter && endingBefore) {
    return new ChatbotError(
      "bad_request:api",
      "Only one of starting_after or ending_before can be provided."
    ).toResponse();
  }

  const { userId } = await auth();
  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  try {
    const summaries = await listConversations();
    return Response.json(applyPagination(summaries, limit, startingAfter, endingBefore));
  } catch (err) {
    const code = backendErrorToCode(err);
    const cause = err instanceof BackendError ? err.detail : undefined;
    return new ChatbotError(code, cause).toResponse();
  }
}

export async function DELETE() {
  const { userId } = await auth();
  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  try {
    const deletedCount = await deleteAllConversations();
    return Response.json({ success: true, deletedCount }, { status: 200 });
  } catch (err) {
    const code = backendErrorToCode(err);
    const cause = err instanceof BackendError ? err.detail : undefined;
    return new ChatbotError(code, cause).toResponse();
  }
}