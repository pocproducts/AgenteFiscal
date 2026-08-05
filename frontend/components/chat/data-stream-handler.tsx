"use client";

import { useEffect } from "react";
import { useSWRConfig } from "swr";
import { unstable_serialize } from "swr/infinite";
import type { AgentTask } from "@/hooks/use-agent-sidebar";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { initialArtifactData, useArtifact } from "@/hooks/use-artifact";
import { artifactDefinitions } from "./artifact";
import { useDataStream } from "./data-stream-provider";
import { getChatHistoryPaginationKey } from "./sidebar-history";

// ─────────────────────────────────────────────────────────────────────────────
// Shared SWR-based mutator for agent sidebar — avoids circular deps by calling
// the SWR mutate directly instead of going through the hook (which would create
// an extra subscription inside DataStreamHandler).
// ─────────────────────────────────────────────────────────────────────────────

export function DataStreamHandler() {
  const { dataStream, setDataStream } = useDataStream();
  const { mutate } = useSWRConfig();

  const { artifact, setArtifact, setMetadata } = useArtifact();
  const { updateTask, updateSession } = useAgentSidebar();

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

      if (anyDelta.type === "data-agent-session-start") {
        const { agentId, toolName, profileId, tasks } = anyDelta.data as {
          agentId: string;
          toolName: string;
          profileId?: string;
          toolKey: string;
          tasks: Array<{ id: string; label: string }>;
        };

        mutate(
          "agent-sidebar",
          (prev: any) => {
            const current = prev ?? {
              isOpen: false,
              activeAgentId: null,
              sessions: {},
            };

            const hydratedTasks: AgentTask[] = tasks.map((t) => ({
              ...t,
              status: "pending" as const,
            }));

            const newSession = {
              agentId,
              toolName,
              profileId,
              messageId: "",
              status: "running" as const,
              tasks: hydratedTasks,
              startedAt: Date.now(),
              totalCostCents: 0,
            };

            return {
              ...current,
              isOpen: true,
              activeAgentId: agentId,
              sessions: { ...current.sessions, [agentId]: newSession },
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

        updateTask(agentId, taskId, { status, durationMs, costCents });
        continue;
      }

      // ── Agent session complete ────────────────────────────────────────────
      if (anyDelta.type === "data-agent-session-complete") {
        const { agentId } = anyDelta.data as {
          agentId: string;
          durationMs: number;
        };

        updateSession(agentId, {
          status: "completed",
          completedAt: Date.now(),
        });
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
    updateTask,
    updateSession,
  ]);

  return null;
}
