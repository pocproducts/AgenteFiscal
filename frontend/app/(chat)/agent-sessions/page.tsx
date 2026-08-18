"use client";

import { Activity, Clock, Cpu, Tag, Target, UserIcon } from lucide-react;
import { Badge } from "@/components/ui/badge";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { useLiveClock } from "@/hooks/use-live-clock";
import { useProfiles } from "@/hooks/use-profiles";
import { formatClock } from "@/lib/agent-window";
import { useLanguage } from "@/lib/i18n";

// Tipos para tareas de agente
type AgentTask = {
  id: string;
  label: string;
  status: "pending" | "running" | "completed" | "error";
  durationMs?: number;
  costCents?: number;
};

type AgentSession = {
  agentId: string;
  toolName: string;
  profileId?: string;
  messageId: string;
  status: "idle" | "running" | "completed" | "error";
  tasks: AgentTask[];
  totalCostCents: number;
  startedAt?: number;
  completedAt?: number;
};

// Helper to get profile name
const getProfileName = (profileId: string | undefined): string => {
  if (!profileId) {
    return "—";
  }
  // En producción, esto vendría del state de profiles
  return profileId;
};

// Helper to get task summary
const getTaskSummary = (tasks: AgentTask[]): string => {
  if (!tasks || tasks.length === 0) {
    return "—";
  }
  const running = tasks.filter((t) => t.status === "running").length;
  const completed = tasks.filter((t) => t.status === "completed").length;
  const failed = tasks.filter((t) => t.status === "error").length;
  const pending = tasks.length - running - completed - failed;

  const parts: string[] = [];
  if (running > 0) parts.push(`${running} running`);
  if (completed > 0) parts.push(`${completed} completed`);
  if (failed > 0) parts.push(`${failed} failed`);
  if (pending > 0) parts.push(`${pending} pending`);

  return parts.length > 0 ? parts.join(", ") : "—";
};

export default function AgentSessionsPage() {
  const { allSessions } = useAgentSidebar();
  const { profiles } = useProfiles();
  const { t } = useLanguage();
  const dict = t.panel.pages.dashboards;

  const sortedSessions: AgentSession[] = [...allSessions].sort(
    (a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0)
  );

  // Live wall-clock: the duration column ticks in real time while any session
  // is running, matching the chat sidebar clock.
  const anyRunning = sortedSessions.some((s) => s.status === "running");
  const nowMs = useLiveClock(anyRunning);

  return (
    <div className="flex flex-1 flex-col h-full bg-background/50">
      <div className="flex items-center gap-4 border-b border-border/40 px-6 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
          <Activity className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">
            {dict.title}
          </h1>
          <p className="text-sm text-muted-foreground">{dict.description}</p>
        </div>
      </div>

      <div className="flex-1 p-6">
        <div className="rounded-xl border border-border/50 bg-background/50 shadow-sm overflow-hidden">
          <table className="w-full text-left text-sm whitespace-nowrap">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-5 py-3.5 font-medium">
                  <div className="flex items-center gap-1.5">
                    <Target className="size-4 shrink-0" /> {getTaskSummary(sortedSessions[0]?.tasks ?? [])}
                  </div>
                </th>
                <th className="px-5 py-3.5 font-medium">
                  <div className="flex items-center gap-1.5">
                    <Tag className="size-4 shrink-0" /> {dict.sessionId}
                  </div>
                </th>
                <th className="px-5 py-3.5 font-medium">
                  <div className="flex items-center gap-1.5">
                    <UserIcon className="size-4 shrink-0" /> {dict.profileId}
                  </div>
                </th>
                <th className="px-5 py-3.5 font-medium">
                  <div className="flex items-center gap-1.5">
                    <Clock className="size-4 shrink-0" /> {dict.startedAt}
                  </div>
                </th>
                <th className="px-5 py-3.5 font-medium">
                  <div className="flex items-center gap-1.5">
                    <Activity className="size-4 shrink-0" /> {dict.duration}
                  </div>
                </th>
                <th className="px-5 py-3.5 font-medium">
                  <div className="flex items-center gap-1.5">
                    <Activity className="size-4 shrink-0" /> {dict.cost}
                  </div>
                </th>
                <th className="px-5 py-3.5 font-medium">
                  <div className="flex items-center gap-1.5">
                    <Cpu className="size-4 shrink-0" /> {dict.status}
                  </div>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {sortedSessions.map((s: AgentSession, i: number) => {
                const totalCostUsd = s.totalCostCents / 100;
                const duration = s.startedAt
                  ? formatClock((s.completedAt ?? nowMs) - s.startedAt)
                  : "—";

                const startedString = s.startedAt
                  ? new Date(s.startedAt).toLocaleString()
                  : "—";

                return (
                  <tr
                    className="hover:bg-muted/10 transition-colors"
                    key={s.agentId ?? i}
                  >
                    <td className="px-5 py-4 text-foreground font-medium flex items-center gap-2">
                      <span
                        className={`h-2 w-2 rounded-full ${s.status === "running" ? "bg-amber-400 animate-pulse" : s.status === "completed" ? "bg-emerald-500" : "bg-muted-foreground/40"}`}
                      />
                      Ejecutar {s.toolName}
                    </td>
                    <td className="px-5 py-4 font-mono text-xs text-muted-foreground">
                      {s.agentId}
                    </td>
                    <td className="px-5 py-4">
                      <Badge
                        className="py-0.5 px-2 font-medium text-xs border-muted-foreground/20 bg-muted/40"
                        variant="outline"
                      >
                        {getProfileName(s.profileId)}
                      </Badge>
                    </td>
                    <td className="px-5 py-4 text-muted-foreground text-xs">
                      {startedString}
                    </td>
                    <td className="px-5 py-4 text-muted-foreground text-xs font-mono">
                      {duration}
                    </td>
                    <td className="px-5 py-4 text-emerald-500 font-mono font-medium">
                      ${totalCostUsd.toFixed(3)}
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-foreground font-medium text-xs">
                          {getLastTaskLabel(s.tasks)}
                        </span>
                        <span className="text-[10px] text-muted-foreground font-mono">
                          {dict.statusLabel} {s.status.toUpperCase()}
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {sortedSessions.length === 0 && (
            <div className="p-12 text-center text-muted-foreground italic bg-muted/5">
              {dict.empty}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
