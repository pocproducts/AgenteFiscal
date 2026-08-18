import { auth } from "@clerk/nextjs/server";
import {
  getConversation,
  type BackendConversationMessage,
} from "@/lib/backend/conversations";
import { BackendError } from "@/lib/backend/client";
import { ChatbotError, type ErrorCode } from "@/lib/errors";
import type { ChatMessage } from "@/lib/types";

// ── Real backend messages BFF ───────────────────────────────────────────────
// Consumes GET /v1/conversations/{id} (Postgres) with the user's Clerk JWT via
// the server-only client, and maps the backend messages to the UI shape the
// chat hook consumes (use-active-chat.tsx). The ephemeral mock is gone.

function toUIMessage(message: BackendConversationMessage): ChatMessage {
  return {
    id: message.id,
    role: (message.role as "user" | "assistant" | "system") || "user",
    // Backend messages store parts as a {content, role} dict; the UI contract
    // expects an array of parts, so fall back to a text part when needed.
    parts: Array.isArray(message.parts)
      ? (message.parts as unknown as ChatMessage["parts"])
      : [{ type: "text", text: message.content || "" }],
    metadata: {
      createdAt: message.createdAt ?? new Date().toISOString(),
    },
  };
}

function backendErrorToCode(err: unknown): ErrorCode {
  if (err instanceof BackendError) {
    if (err.status === 401 || err.status === 403) {
      return "unauthorized:chat";
    }
    if (err.status === 404) {
      return "not_found:chat";
    }
    if (err.status >= 400 && err.status < 500) {
      return "bad_request:chat";
    }
    return "offline:chat";
  }
  return "offline:chat";
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const chatId = searchParams.get("chatId");

  if (!chatId) {
    return new ChatbotError(
      "bad_request:api",
      "Parameter chatId is required."
    ).toResponse();
  }

  const { userId } = await auth();
  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  try {
    const conversation = await getConversation(chatId);

    if (!conversation) {
      return new ChatbotError("not_found:chat").toResponse();
    }

    return Response.json({
      messages: conversation.messages.map(toUIMessage),
      visibility: "private",
      userId,
      isReadonly: false,
      // Per-chat agent activity is streamed live (data-agent-session-*); the
      // backend does not persist it on the conversation yet.
      activity: [],
    });
  } catch (err) {
    const code = backendErrorToCode(err);
    const cause = err instanceof BackendError ? err.detail : undefined;
    return new ChatbotError(code, cause).toResponse();
  }
}