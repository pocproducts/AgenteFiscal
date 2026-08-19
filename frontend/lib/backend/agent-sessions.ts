// server-only: never import this from client components.
// Typed, envelope-free helpers for the backend /v1/agent-sessions telemetry API
// (AST-6). Consumed by the BFF routes under app/(chat)/api/agent-sessions and
// app/(chat)/api/messages; they rely on callBackend, which holds the Clerk JWT
// and must never reach the browser.
//
// The backend returns snake_case rows (see ports/agent_sessions.py model_dump);
// mapAgentSessionRow projects them to the camelCase shape the UI consumes and
// toAgentSessionSnapshots maps them back to the AgentSessionSnapshot contract
// useAgentSidebar.hydrate already understands (chat reload persistence).

import { callBackend } from "@/lib/backend/client";
import { TOOL_NAMES } from "@/lib/agent-window";
import type {
  AgentSessionSnapshot,
  AgentTask,
} from "@/lib/ai/tools/agent-execution";

/** Raw persisted row as returned by GET /v1/agent-sessions (snake_case keys). */
export interface BackendAgentSessionRow {
  id: string;
  tool: string;
  message_id: string | null;
  conversation_id: string | null;
  profile_id: string | null;
  tenant_id: string;
  user_id: string | null;
  session_id: string | null;
  status: string;
  tasks: Array<{ task: string; label: string; status: string }>;
  cost_cents: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

/** camelCase projection of a persisted row, consumed by the agent-sessions page. */
export interface AgentSessionRow {
  id: string;
  tool: string;
  messageId: string | null;
  conversationId: string | null;
  profileId: string | null;
  tenantId: string;
  userId: string | null;
  sessionId: string | null;
  status: string;
  tasks: Array<{ task: string; label: string; status: string }>;
  costCents: number;
  startedAt: string | null;
  completedAt: string | null;
  createdAt: string | null;
}

export interface ListAgentSessionsOptions {
  /** Scope the listing to one chat (chat hydrate consumes this). */
  conversationId?: string;
  /** Cap the window (backend default 100, max 200). */
  limit?: number;
}

/** Project a snake_case backend row into the camelCase UI contract (AST-6). */
export function mapAgentSessionRow(
  row: BackendAgentSessionRow
): AgentSessionRow {
  return {
    id: row.id,
    tool: row.tool,
    messageId: row.message_id,
    conversationId: row.conversation_id,
    profileId: row.profile_id,
    tenantId: row.tenant_id,
    userId: row.user_id,
    sessionId: row.session_id,
    status: row.status,
    tasks: row.tasks,
    costCents: row.cost_cents,
    startedAt: row.started_at,
    completedAt: row.completed_at,
    createdAt: row.created_at,
  };
}

/**
 * Map persisted rows to the AgentSessionSnapshot contract used by
 * useAgentSidebar.hydrate (AST-6). Each row id becomes the snapshot agentId so
 * reloads dedupe against live in-memory sessions; engine rows carry NULL
 * session/profile ids (AST-3) and are rendered as dashes by the page.
 */
export function toAgentSessionSnapshots(
  rows: BackendAgentSessionRow[]
): AgentSessionSnapshot[] {
  return rows.map((row) => ({
    agentId: row.id,
    toolKey: row.tool,
    toolName: TOOL_NAMES[row.tool] ?? row.tool,
    tasks: row.tasks.map(
      (t): AgentTask => ({
        id: t.task,
        label: t.label,
        // Backend persists only the final run status onto every task entry
        // (build_session_tasks); anything else is treated as completed.
        status: t.status === "error" ? "error" : "completed",
      })
    ),
    startedAt: row.started_at ? new Date(row.started_at).getTime() : undefined,
    completedAt: row.completed_at
      ? new Date(row.completed_at).getTime()
      : undefined,
    totalCostCents: row.cost_cents,
  }));
}

/**
 * List persisted agent runs for the authenticated tenant/user, newest first.
 * The backend returns a bare JSON array (not a UnifiedResponse envelope) so
 * Array.isArray() can be used directly.
 */
export async function listAgentSessions(
  options: ListAgentSessionsOptions = {}
): Promise<BackendAgentSessionRow[]> {
  const params = new URLSearchParams();
  if (options.conversationId) {
    params.set("conversation_id", options.conversationId);
  }
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  const qs = params.toString();
  const res = await callBackend<BackendAgentSessionRow[]>(
    `/v1/agent-sessions${qs ? `?${qs}` : ""}`,
    { timeoutMs: 60_000 }
  );
  return Array.isArray(res) ? res : [];
}