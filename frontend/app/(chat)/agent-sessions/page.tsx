"use client";

import { Activity, Clock, Cpu, Tag, Target, UserIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useAgentSessions } from "@/hooks/use-agent-sessions";
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
  /** Provider session id from the persisted row; engines keep it empty (AST-3). */
  sessionId?: string;
};

// Remove the stub helper — profile names are resolved from the profiles hook.
// Helper to get last task label
const getLastTaskLabel = (tasks: AgentTask[]): string => {
  if (!tasks || tasks.length === 0) {
    return "—";
  }
  return tasks[tasks.length - 1]?.label ?? "—";
};

export default function AgentSessionsPage() {
  const { sessions } = useAgentSessions();
  const { profiles } = useProfiles();
  const { t } = useLanguage();
  const dict = t.panel.pages.dashboards;

  const sortedSessions: AgentSession[] = [...sessions].sort(
    (a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0)
  );

  const profileNameById = (profileId: string | undefined): string => {
    if (!profileId) return "—";
    return profiles.find((p) => p.id === profileId)?.name ?? "—";
  };

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
                    <Target className="size-4 shrink-0" /> {dict.acciones}
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

                // Acciones: task count + last label from the persisted JSONB
                // (AST-3 — engines persist the canonical 7 defaults).
                const acciones =
                  s.tasks.length > 0
                    ? `${s.tasks.length} · ${getLastTaskLabel(s.tasks)}`
                    : "—";

                return (
                  <tr
                    className="hover:bg-muted/10 transition-colors"
                    key={s.agentId ?? i}
                  >
                    <td className="px-5 py-4 text-foreground">
                      <div className="flex flex-col gap-0.5">
                        <span className="font-medium flex items-center gap-2">
                          <span
                            className={`h-2 w-2 rounded-full ${s.status === "running" ? "bg-amber-400 animate-pulse" : s.status === "completed" ? "bg-emerald-500" : "bg-muted-foreground/40"}`}
                          />
                          Ejecutar {s.toolName}
                        </span>
                        <span className="text-[10px] pl-4 text-muted-foreground font-mono">
                          {acciones}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-4 font-mono text-xs text-muted-foreground">
                      {s.sessionId ?? "-"}
                    </td>
                    <td className="px-5 py-4">
                      <Badge
                        className="py-0.5 px-2 font-medium text-xs border-muted-foreground/20 bg-muted/40"
                        variant="outline"
                      >
                        {profileNameById(s.profileId)}
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
                      <div className="flex items-center gap-2">
                        <span
                          className={`inline-block h-2 w-2 rounded-full ${
                            s.status === "running"
                              ? "bg-amber-400 animate-pulse"
                              : s.status === "completed"
                                ? "bg-emerald-500"
                                : s.status === "error"
                                  ? "bg-red-500"
                                  : "bg-muted-foreground/40"
                          }`}
                        />
                        <span className="text-foreground font-medium text-xs uppercase">
                          {s.status}
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
