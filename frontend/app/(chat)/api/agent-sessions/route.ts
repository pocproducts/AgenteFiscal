import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import {
  listAgentSessions,
  mapAgentSessionRow,
} from "@/lib/backend/agent-sessions";
import { BackendError } from "@/lib/backend/client";
import { ChatbotError, type ErrorCode } from "@/lib/errors";

// ── Agent sessions BFF ───────────────────────────────────────────────────────
// Proxies GET /v1/agent-sessions (Postgres-persisted tool-run telemetry, AST-6)
// with the user's Clerk JWT via the server-only client, projecting the backend
// snake_case rows into the camelCase shape the page consumes. The page and the
// use-agent-sessions hook read ONLY this route — never the backend directly.

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

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const conversationId = searchParams.get("conversation_id") ?? undefined;
  const limit = Math.min(
    Math.max(Number.parseInt(searchParams.get("limit") || "100", 10), 1),
    200
  );

  const { userId } = await auth();
  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  try {
    const rows = await listAgentSessions({ conversationId, limit });
    return Response.json(rows.map(mapAgentSessionRow));
  } catch (err) {
    const code = backendErrorToCode(err);
    const cause = err instanceof BackendError ? err.detail : undefined;
    return new ChatbotError(code, cause).toResponse();
  }
}