"use client";

import { CheckCircle2, Loader2 } from "lucide-react";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { useArtifact } from "@/hooks/use-artifact";
import { cn } from "@/lib/utils";

export const AgenteTrabajandoButton = ({
  toolName,
  toolKey,
  messageId,
}: {
  toolName: string;
  toolKey: string;
  messageId: string;
}) => {
  const {
    allSessions,
    setActiveAgent,
    open: openAgentSidebar,
  } = useAgentSidebar();
  const { setArtifact } = useArtifact();

  // Find the session for THIS chat message: prefer the one created for this
  // messageId (the merged optimistic session keeps it), then the most recent
  // matching tool run. First-match by toolName alone could re-open an old
  // completed session from a previous message.
  const normalizedToolName = toolName.toLowerCase().replace(/[^a-z]/g, "");
  const matching = allSessions.filter(
    (s) =>
      s.toolName.toLowerCase().replace(/[^a-z]/g, "") === normalizedToolName
  );
  const session =
    matching.find((s) => s.messageId === messageId) ??
    [...matching].sort(
      (a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0)
    )[0] ??
    null;

  const isCompleted = session?.status === "completed";

  const handleOpen = () => {
    setArtifact((prev) => ({ ...prev, isVisible: false }));
    if (session) {
      // Session already exists in store — just switch to it
      setActiveAgent(session.agentId);
    } else {
      // First click before stream event arrives — open optimistically
      openAgentSidebar(messageId, toolName, toolKey);
    }
  };

  return (
    <button
      className={cn(
        "inline-flex items-center gap-2 my-1.5 px-3 py-1.5 rounded-lg border font-medium text-xs text-left w-fit transition-all duration-300 shadow-sm hover:shadow-md active:scale-[0.98]",
        isCompleted
          ? "border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
          : "border-primary/20 bg-primary/5 hover:bg-primary/10 text-primary cursor-pointer"
      )}
      onClick={handleOpen}
      type="button"
    >
      {isCompleted ? (
        <CheckCircle2 className="size-3.5 text-emerald-500 shrink-0" />
      ) : (
        <Loader2 className="size-3.5 animate-spin text-primary shrink-0" />
      )}
      <span className={cn("italic", isCompleted && "not-italic font-semibold")}>
        {isCompleted
          ? `${toolName} completado ✓`
          : `Agente trabajando en ${toolName}...`}
      </span>
    </button>
  );
};
