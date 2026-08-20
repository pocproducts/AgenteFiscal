"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/utils";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { TOOL_NAMES } from "@/lib/agent-window";
import type { AgentSession, AgentTask } from "@/lib/ai/tools/agent-execution";
import type { AgentSessionRow } from "@/lib/backend/agent-sessions";

// ── Persisted agent-sessions data hook (AST-6) ───────────────────────────────
// Fetches the BFF proxy (app/(chat)/api/agent-sessions) — persisted backend
// telemetry rows — and merges the live in-memory sessions from the agent
// sidebar so the page shows streaming runs AND reload-surviving history in one
// list. Persisted rows are authoritative once a run completes: a completed/
// error live session of a tool that already has a persisted row is replaced by
// the backend state (dedupe by row id, plus collapse by tool for the window
// after a run finishes but before live SWR state is cleared).

const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** Page-facing session entry: persisted row projected + live sidebar session. */
export type AgentSessionEntry = AgentSession & { sessionId?: string };

function rowToSession(row: AgentSessionRow): AgentSessionEntry {
  return {
    agentId: row.id,
    toolName: TOOL_NAMES[row.tool] ?? row.tool,
    profileId: row.profileId ?? undefined,
    messageId: row.messageId ?? "",
    status: (row.status as AgentSession["status"]) || "completed",
    tasks: row.tasks.map(
      (t): AgentTask => ({
        id: t.task,
        label: t.label,
        status: (t.status as AgentTask["status"]) || "completed",
      })
    ),
    totalCostCents: row.costCents,
    startedAt: row.startedAt ? new Date(row.startedAt).getTime() : undefined,
    completedAt: row.completedAt
      ? new Date(row.completedAt).getTime()
      : undefined,
    sessionId: row.sessionId ?? undefined,
  };
}

export function useAgentSessions() {
  const { data: rows, error } = useSWR<AgentSessionRow[]>(
    `${basePath}/api/agent-sessions`,
    fetcher
  );
  const { allSessions } = useAgentSidebar();

  const sessions = useMemo(() => {
    const persisted = (rows ?? []).map(rowToSession);
    const persistedIds = new Set(persisted.map((s) => s.agentId));
    const persistedTools = new Set(persisted.map((s) => s.toolName));

    const live = allSessions.filter(
      (s) =>
        !persistedIds.has(s.agentId) &&
        // Persisted rows are authoritative for finished runs: once the backend
        // has written the row (revalidation after a run), the completed live
        // copy is redundant. Running/idle sessions stay until they finish.
        !(
          persistedTools.has(s.toolName) &&
          (s.status === "completed" || s.status === "error")
        )
    );

    return [...live, ...persisted].sort(
      (a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0)
    );
  }, [rows, allSessions]);

  return {
    sessions,
    isLoading: !rows && !error,
    error,
  };
}