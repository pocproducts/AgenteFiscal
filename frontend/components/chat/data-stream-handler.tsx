"use client";

import { useEffect, useRef } from "react";
import { useSWRConfig } from "swr";
import { unstable_serialize } from "swr/infinite";
import type {
  AgentSession,
  AgentSidebarState,
  AgentTask,
} from "@/hooks/use-agent-sidebar";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { initialArtifactData, useArtifact } from "@/hooks/use-artifact";
import { useTenantKey } from "@/hooks/use-tenant-key";
import { artifactDefinitions } from "./artifact";
import { useDataStream } from "./data-stream-provider";
import { getChatHistoryPaginationKey } from "./sidebar-history";

// ─────────────────────────────────────────────────────────────────────────────
// Server agentId → local agentId remap
// The route streams its own server-generated agentId; the client already owns
// an optimistic session (created by openAgentSidebar) with a DIFFERENT local id.
// We record the mapping on session-start and resolve every later stream event
// through it, so the dynamic steps/liveUrl land on the SAME session instead of
// creating a duplicate. The map is keyed by server id so StrictMode double-runs
// (which replay the same batch of deltas) stay idempotent.
// ─────────────────────────────────────────────────────────────────────────────

function normalizeToolName(toolName: string): string {
  return toolName.toLowerCase().replace(/[^a-z]/g, "");
}

function resolveAgentId(
  map: Record<string, string>,
  serverAgentId: string
): string {
  return map[serverAgentId] ?? serverAgentId;
}

// Locate the optimistic session a session-start event should merge into: same
// normalized tool name AND status "idle" (the just-created placeholder). We
// never merge onto a completed/running session from a previous run. Sessions
// keep insertion order in the map, so the LAST idle match is the most recent.
function findIdleMergeTarget(
  state: AgentSidebarState | undefined,
  toolName: string
): AgentSession | undefined {
  if (!state) {
    return undefined;
  }
  const normalized = normalizeToolName(toolName);
  let target: AgentSession | undefined;
  for (const session of Object.values(state.sessions)) {
    if (
      session.status === "idle" &&
      normalizeToolName(session.toolName) === normalized
    ) {
      target = session;
    }
  }
  return target;
}

// Used to prepare the initial fallback state shape in mutate updaters.
const EMPTY_SIDEBAR_STATE = {
  isOpen: false,
  activeAgentId: null,
  sessions: {} as Record<string, AgentSession>,
};

// ─────────────────────────────────────────────────────────────────────────────
// Shared SWR-based mutator for agent sidebar — avoids circular deps by calling
// the SWR mutate directly instead of going through the hook (which would create
// an extra subscription inside DataStreamHandler).
// ─────────────────────────────────────────────────────────────────────────────

export function DataStreamHandler() {
  const { dataStream, setDataStream } = useDataStream();
  const { mutate, cache } = useSWRConfig();
  // Maps the stream's server agentId onto the local session id. Filled when
  // data-agent-session-start merges; read by every later agent-stream event.
  const agentIdMapRef = useRef<Record<string, string>>({});

  const { artifact, setArtifact, setMetadata } = useArtifact();
  const { updateTask, updateSession } = useAgentSidebar();
  // Must match the key useAgentSidebar() reads from (hooks/use-agent-sidebar.ts)
  // — mutating a different key here would silently write into a cache slot
  // updateTask/updateSession never look at.
  const agentSidebarKey = useTenantKey("agent-sidebar");

  useEffect(() => {
    if (!dataStream?.length) {
      return;
    }

    const newDeltas = dataStream.slice();
    setDataStream([]);

    for (const delta of newDeltas) {
      // ── Chat history refresh ─────────────────────────────────────────────
      if (delta.type === "data-chat-title") {
        mutate(unstable_serialize(getChatHistoryPaginationKey));
        continue;
      }

      // ── Agent session start ──────────────────────────────────────────────
      // Note: custom data-agent-* types are not part of the SDK union; cast through any.
      const anyDelta = delta as any;

      if (anyDelta.type === "data-agent-session-start" && agentSidebarKey) {
        const { agentId, toolName, profileId, tasks, liveUrl, windowMs } =
          anyDelta.data as {
            agentId: string;
            toolName: string;
            profileId?: string;
            tasks: Array<{ id: string; label: string }>;
            liveUrl?: string;
            windowMs?: number;
          };

        // Resolve which LOCAL session this stream maps onto. First check the
        // map so a StrictMode double-run of the same batch never forks into a
        // second session (the optimistic one is no longer idle by then).
        let localAgentId = agentIdMapRef.current[agentId];
        if (!localAgentId) {
          const prev = cache
            ? (cache.get(agentSidebarKey)?.data as
                | AgentSidebarState
                | undefined)
            : undefined;
          const idleSession = findIdleMergeTarget(prev, toolName);
          localAgentId = idleSession?.agentId ?? agentId;
          agentIdMapRef.current[agentId] = localAgentId;
        }

        const hydratedTasks: AgentTask[] = tasks.map((t) => ({
          ...t,
          status: "pending" as const,
        }));

        mutate(
          agentSidebarKey,
          (prev: any) => {
            const current = prev ?? EMPTY_SIDEBAR_STATE;
            const existing = current.sessions?.[localAgentId];

            // Merged: patch the optimistic session in place — keep its real
            // messageId, clear the static placeholder tasks (the dynamic steps
            // arrive via data-agent-browser-step). Fallback: brand-new session
            // keyed by the server agentId (identity mapping).
            const newSession = existing
              ? {
                  ...existing,
                  status: "running" as const,
                  startedAt: Date.now(),
                  tasks: hydratedTasks,
                  profileId: profileId ?? existing.profileId,
                  liveUrl: liveUrl ?? undefined,
                  windowMs,
                }
              : {
                  agentId: localAgentId,
                  toolName,
                  profileId,
                  messageId: "",
                  status: "running" as const,
                  tasks: hydratedTasks,
                  startedAt: Date.now(),
                  totalCostCents: 0,
                  liveUrl: liveUrl ?? undefined,
                  windowMs,
                };

            return {
              ...current,
              isOpen: true,
              activeAgentId: localAgentId,
              sessions: { ...current.sessions, [localAgentId]: newSession },
            };
          },
          { revalidate: false }
        );

        continue;
      }

      // ── Agent task update ────────────────────────────────────────────────
      if (anyDelta.type === "data-agent-task-update") {
        const { agentId, taskId, status, durationMs, costCents } =
          anyDelta.data as {
            agentId: string;
            taskId: string;
            status: "running" | "completed" | "error";
            durationMs?: number;
            costCents?: number;
          };

        updateTask(resolveAgentId(agentIdMapRef.current, agentId), taskId, {
          status,
          durationMs,
          costCents,
        });
        continue;
      }

      // ── Agent browser step (live Composio agent actions) ──────────────────
      if (anyDelta.type === "data-agent-browser-step" && agentSidebarKey) {
        const { agentId, step, goal, status } = anyDelta.data as {
          agentId: string;
          step: number;
          goal: string;
          url: string;
          status?: "running" | "finished" | "error";
        };

        const localAgentId = resolveAgentId(agentIdMapRef.current, agentId);
        const stepId = `sr-step-${step}`;
        const trimmedGoal = goal.trim();
        mutate(
          agentSidebarKey,
          (prev: any) => {
            const current = prev ?? EMPTY_SIDEBAR_STATE;
            const session = current.sessions?.[localAgentId];
            if (!session) {
              return current;
            }
            const currentTasks: AgentTask[] = session.tasks ?? [];
            const lastTask = currentTasks.at(-1);
            // Consecutive Composio actions re-emit the SAME goal (the agent keeps
            // polling steps for a single sub-task), which would append one row per
            // step with an identical label. Only open a NEW row when the goal
            // actually changes; otherwise update the running row in place (or mark
            // it completed when this step reports "finished").
            const sameGoal =
              lastTask !== undefined &&
              lastTask.status === "running" &&
              (trimmedGoal === "" || lastTask.label.trim() === trimmedGoal);
            let tasks: AgentTask[];
            if (sameGoal) {
              tasks = currentTasks.map((t: AgentTask, i: number) =>
                i === currentTasks.length - 1
                  ? {
                      ...t,
                      label: trimmedGoal || t.label,
                      status:
                        status === "finished"
                          ? ("completed" as const)
                          : ("running" as const),
                    }
                  : t
              );
            } else {
              tasks = currentTasks.map((t: AgentTask) =>
                t.status === "running"
                  ? { ...t, status: "completed" as const }
                  : t
              );
              if (status === "finished") {
                tasks = tasks.map((t: AgentTask) =>
                  t.id === stepId ? { ...t, status: "completed" as const } : t
                );
              } else if (tasks.some((t: AgentTask) => t.id === stepId)) {
                tasks = tasks.map((t: AgentTask) =>
                  t.id === stepId
                    ? {
                        ...t,
                        label: trimmedGoal || t.label,
                        status: "running" as const,
                      }
                    : t
                );
              } else {
                tasks = [
                  ...tasks,
                  {
                    id: stepId,
                    label: trimmedGoal || `Paso ${step}`,
                    status: "running" as const,
                  },
                ];
              }
            }
            return {
              ...current,
              sessions: {
                ...current.sessions,
                [localAgentId]: { ...session, tasks },
              },
            };
          },
          { revalidate: false }
        );
        continue;
      }

      // ── Agent session complete ────────────────────────────────────────────
      if (anyDelta.type === "data-agent-session-complete" && agentSidebarKey) {
        const { agentId, status } = anyDelta.data as {
          agentId: string;
          durationMs: number;
          status?: "error" | "completed";
        };

        const localAgentId = resolveAgentId(agentIdMapRef.current, agentId);
        const isError = status === "error";
        mutate(
          agentSidebarKey,
          (prev: any) => {
            const current = prev ?? EMPTY_SIDEBAR_STATE;
            const session = current.sessions?.[localAgentId];
            if (!session) {
              return current;
            }
            if (isError) {
              // Business error (e.g. BROWSER_ERROR): surface the ERROR state and
              // leave the current task rows untouched — never mark them completed.
              return {
                ...current,
                sessions: {
                  ...current.sessions,
                  [localAgentId]: {
                    ...session,
                    status: "error" as const,
                    completedAt: Date.now(),
                  },
                },
              };
            }
            const tasks: AgentTask[] = (session.tasks ?? []).map(
              (t: AgentTask) =>
                t.status === "running"
                  ? { ...t, status: "completed" as const }
                  : t
            );
            return {
              ...current,
              sessions: {
                ...current.sessions,
                [localAgentId]: {
                  ...session,
                  status: "completed" as const,
                  completedAt: Date.now(),
                  tasks,
                },
              },
            };
          },
          { revalidate: false }
        );
        continue;
      }

      // ── Agent session live URL (Composio embed) ────────────────────────────
      if (anyDelta.type === "data-agent-session-liveurl") {
        const { agentId, liveUrl } = anyDelta.data as {
          agentId: string;
          liveUrl: string;
        };
        const localAgentId = resolveAgentId(agentIdMapRef.current, agentId);
        updateSession(localAgentId, { liveUrl });
        continue;
      }

      // ── Artifact stream parts ─────────────────────────────────────────────
      const artifactDefinition = artifactDefinitions.find(
        (currentArtifactDefinition) =>
          currentArtifactDefinition.kind === artifact.kind
      );

      if (artifactDefinition?.onStreamPart) {
        artifactDefinition.onStreamPart({
          streamPart: delta,
          setArtifact,
          setMetadata,
        });
      }

      setArtifact((draftArtifact) => {
        if (!draftArtifact) {
          return { ...initialArtifactData, status: "streaming" };
        }

        switch (delta.type) {
          case "data-id":
            return {
              ...draftArtifact,
              documentId: delta.data,
              status: "streaming",
            };

          case "data-title":
            return {
              ...draftArtifact,
              title: delta.data,
              status: "streaming",
            };

          case "data-kind":
            return {
              ...draftArtifact,
              kind: delta.data,
              status: "streaming",
            };

          case "data-clear":
            return {
              ...draftArtifact,
              content: "",
              status: "streaming",
            };

          case "data-finish":
            return {
              ...draftArtifact,
              status: "idle",
            };

          default:
            return draftArtifact;
        }
      });
    }
  }, [
    dataStream,
    setArtifact,
    setMetadata,
    artifact,
    setDataStream,
    mutate,
    cache,
    updateTask,
    updateSession,
    agentSidebarKey,
  ]);

  return null;
}
