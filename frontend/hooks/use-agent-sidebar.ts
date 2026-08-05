"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import type { AgentSession, AgentTask } from "@/lib/ai/tools/agent-execution";
import {
  buildSubtasksForTool,
  generateAgentId,
} from "@/lib/ai/tools/agent-execution";

// ── State ────────────────────────────────────────────────────────────────────

export type { AgentSession, AgentTask };

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
  const { data: localState, mutate: setLocalState } = useSWR<AgentSidebarState>(
    "agent-sidebar",
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
        if (!session) return current;

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
      patch: Partial<Pick<AgentSession, "status" | "startedAt" | "completedAt">>
    ) => {
      setLocalState((prev) => {
        const current = prev ?? initialAgentSidebarState;
        const session = current.sessions[agentId];
        if (!session) return current;

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
      setActiveAgent,
      updateTask,
      updateSession,
    ]
  );
}
