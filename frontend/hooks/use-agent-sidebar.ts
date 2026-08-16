"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import { useTenantKey } from "@/hooks/use-tenant-key";
import {
  type AgentSession,
  type AgentSessionSnapshot,
  type AgentTask,
  buildSubtasksForTool,
  generateAgentId,
} from "@/lib/ai/tools/agent-execution";

// ── State ────────────────────────────────────────────────────────────────────

export type {
  AgentSession,
  AgentSessionSnapshot,
  AgentTask,
} from "@/lib/ai/tools/agent-execution";

export type AgentSidebarState = {
  isOpen: boolean;
  /** The session currently shown in the sidebar */
  activeAgentId: string | null;
  /** All sessions keyed by agentId */
  sessions: Record<string, AgentSession>;
};

const initialAgentSidebarState: AgentSidebarState = {
  isOpen: false,
  activeAgentId: null,
  sessions: {},
};

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useAgentSidebar() {
  const key = useTenantKey("agent-sidebar");
  const { data: localState, mutate: setLocalState } = useSWR<AgentSidebarState>(
    key,
    null,
    { fallbackData: initialAgentSidebarState }
  );

  const state = useMemo(
    () => localState ?? initialAgentSidebarState,
    [localState]
  );

  // ── Open: create a new session and display it ─────────────────────────────

  const open = useCallback(
    (messageId: string, toolName: string, toolKey: string) => {
      const agentId = generateAgentId();
      const newSession: AgentSession = {
        agentId,
        toolName,
        messageId,
        startedAt: Date.now(),
        status: "idle",
        tasks: buildSubtasksForTool(toolKey),
        totalCostCents: 0,
      };

      setLocalState((prev) => {
        const current = prev ?? initialAgentSidebarState;
        return {
          isOpen: true,
          activeAgentId: agentId,
          sessions: { ...current.sessions, [agentId]: newSession },
        };
      });

      return agentId;
    },
    [setLocalState]
  );

  // ── Switch active agent without closing ───────────────────────────────────

  const setActiveAgent = useCallback(
    (agentId: string) => {
      setLocalState((prev) => ({
        ...(prev ?? initialAgentSidebarState),
        isOpen: true,
        activeAgentId: agentId,
      }));
    },
    [setLocalState]
  );

  // ── Update a task within a session ────────────────────────────────────────

  const updateTask = useCallback(
    (
      agentId: string,
      taskId: string,
      patch: Partial<Pick<AgentTask, "status" | "durationMs" | "costCents">>
    ) => {
      setLocalState((prev) => {
        const current = prev ?? initialAgentSidebarState;
        const session = current.sessions[agentId];
        if (!session) {
          return current;
        }

        const tasks = session.tasks.map((t) =>
          t.id === taskId ? { ...t, ...patch } : t
        );

        const totalCostCents = tasks.reduce(
          (acc, t) => acc + (t.costCents ?? 0),
          0
        );

        return {
          ...current,
          sessions: {
            ...current.sessions,
            [agentId]: { ...session, tasks, totalCostCents },
          },
        };
      });
    },
    [setLocalState]
  );

  // ── Update session-level status ───────────────────────────────────────────

  const updateSession = useCallback(
    (
      agentId: string,
      patch: Partial<
        Pick<
          AgentSession,
          "status" | "startedAt" | "completedAt" | "liveUrl" | "windowMs"
        >
      >
    ) => {
      setLocalState((prev) => {
        const current = prev ?? initialAgentSidebarState;
        const session = current.sessions[agentId];
        if (!session) {
          return current;
        }

        return {
          ...current,
          sessions: {
            ...current.sessions,
            [agentId]: { ...session, ...patch },
          },
        };
      });
    },
    [setLocalState]
  );

  // ── Close sidebar (session data is kept in state) ─────────────────────────

  const close = useCallback(() => {
    setLocalState((prev) => ({
      ...(prev ?? initialAgentSidebarState),
      isOpen: false,
    }));
  }, [setLocalState]);

  // ── Hydrate completed sessions from a chat's persisted activity ───────────
  // Restores the monitor after a reload. Merges into the existing sessions map
  // so live in-memory sessions are never wiped. Leaves the sidebar closed; the
  // tabs/count reflect allSessions once the monitor is opened.

  const hydrate = useCallback(
    (chatId: string, activity: AgentSessionSnapshot[]) => {
      setLocalState((prev) => {
        const current = prev ?? initialAgentSidebarState;
        const sessions = { ...current.sessions };

        for (const snapshot of activity) {
          const agentId =
            snapshot.agentId ||
            `agent-${chatId.slice(0, 8)}-${snapshot.toolKey}`;
          const existing = sessions[agentId];

          const tasks: AgentTask[] = snapshot.tasks.map((t) => ({
            id: t.id,
            label: t.label,
            status: t.status ?? "completed",
            durationMs: t.durationMs,
            costCents: t.costCents,
          }));

          sessions[agentId] = {
            ...existing,
            agentId,
            toolName: snapshot.toolName,
            messageId: existing?.messageId ?? "",
            status: "completed",
            tasks,
            startedAt: snapshot.startedAt,
            completedAt: snapshot.completedAt,
            totalCostCents: snapshot.totalCostCents,
            windowMs: snapshot.windowMs,
          };
        }

        return { ...current, sessions };
      });
    },
    [setLocalState]
  );

  // ── Derived helpers ───────────────────────────────────────────────────────

  const activeSession = state.activeAgentId
    ? (state.sessions[state.activeAgentId] ?? null)
    : null;

  const allSessions = Object.values(state.sessions);

  return useMemo(
    () => ({
      isOpen: state.isOpen,
      activeAgentId: state.activeAgentId,
      activeSession,
      allSessions,
      sessions: state.sessions,
      open,
      close,
      hydrate,
      setActiveAgent,
      updateTask,
      updateSession,
    }),
    [
      state.isOpen,
      state.activeAgentId,
      activeSession,
      allSessions,
      state.sessions,
      open,
      close,
      hydrate,
      setActiveAgent,
      updateTask,
      updateSession,
    ]
  );
}
