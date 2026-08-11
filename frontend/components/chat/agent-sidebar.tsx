"use client";

import {
  CheckCircle2,
  CircleDashed,
  Clock,
  Cpu,
  DollarSign,
  ExternalLink,
  Globe,
  ListChecks,
  Loader2,
  RefreshCw,
  Shield,
  X,
} from "lucide-react";
import type { AgentSession, AgentTask } from "@/hooks/use-agent-sidebar";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { useLanguage } from "@/lib/i18n";
import { cn, interpolate } from "@/lib/utils";

// ── Tool URL mapping for the embedded browser ─────────────────────────────────

const TOOL_URLS: Record<
  string,
  { url: string; label: string; favicon: string }
> = {
  consultaarca: {
    url: "https://auth.afip.gob.ar/contribuyente/",
    label: "ARCA — Consulta de Obligaciones",
    favicon: "🏛️",
  },
  sistemaregistral: {
    url: "https://sdr.afip.gob.ar/",
    label: "ARCA — Sistema Registral",
    favicon: "📋",
  },
  misfacilidades: {
    url: "https://www.afip.gob.ar/mf/",
    label: "ARCA — Mis Facilidades",
    favicon: "💳",
  },
  deudavencimientos: {
    url: "https://www.afip.gob.ar/dv/",
    label: "ARCA — Deuda y Vencimientos",
    favicon: "📅",
  },
  rentascordoba: {
    url: "https://www.rentascordoba.gob.ar/",
    label: "Rentas Córdoba — IIBB",
    favicon: "🏢",
  },
  calendariovencimientosarca: {
    url: "https://www.afip.gob.ar/genericos/vencimientos/",
    label: "ARCA — Calendario Fiscal",
    favicon: "📆",
  },
};

function getToolMeta(toolName: string) {
  const key = toolName.toLowerCase().replace(/[^a-z]/g, "");
  return (
    TOOL_URLS[key] ??
    TOOL_URLS[toolName.toLowerCase()] ?? {
      url: "https://fiscalis.arca.gob.ar/",
      label: toolName,
      favicon: "🌐",
    }
  );
}

// ── helpers ───────────────────────────────────────────────────────────────────

function formatDuration(ms?: number): string {
  if (!ms) {
    return "—";
  }
  if (ms < 1000) {
    return `${ms}ms`;
  }
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatCost(cents: number): string {
  if (cents === 0) {
    return "$0.00";
  }
  return `$${(cents / 100).toFixed(4)}`;
}

function sessionElapsed(session: AgentSession): string {
  if (!session.startedAt) {
    return "—";
  }
  const end = session.completedAt ?? Date.now();
  return formatDuration(end - session.startedAt);
}

// ── EmbeddedBrowser ────────────────────────────────────────────────────────────

function EmbeddedBrowser({ session }: { session: AgentSession }) {
  const { t } = useLanguage();
  const meta = getToolMeta(session.toolName);
  const isCompleted = session.status === "completed";
  const isRunning = session.status === "running";
  const agent = t.panel.sidebar.agent;

  return (
    <div className="rounded-xl border border-border/40 bg-background overflow-hidden shadow-sm">
      {/* Browser chrome bar */}
      <div className="flex items-center gap-2 border-b border-border/30 bg-muted/40 px-3 py-2">
        {/* Traffic lights */}
        <div className="flex items-center gap-1.5 shrink-0">
          <div className="size-2.5 rounded-full bg-destructive/50" />
          <div className="size-2.5 rounded-full bg-yellow-400/50" />
          <div
            className={cn(
              "size-2.5 rounded-full transition-colors duration-500",
              isCompleted ? "bg-emerald-500" : "bg-muted-foreground/20"
            )}
          />
        </div>

        {/* URL bar */}
        <div className="flex flex-1 items-center gap-1.5 rounded-md border border-border/30 bg-background/60 px-2 py-1 min-w-0">
          <Shield className="size-2.5 text-emerald-500 shrink-0" />
          <span className="text-[10px] text-muted-foreground truncate font-mono">
            {meta.url}
          </span>
        </div>

        {/* Reload / spinner */}
        <button
          aria-label={agent.reload}
          className="shrink-0 flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
          type="button"
        >
          {isRunning ? (
            <Loader2 className="size-3 animate-spin" />
          ) : (
            <RefreshCw className="size-3" />
          )}
        </button>

        <button
          aria-label={agent.openInNewTab}
          className="shrink-0 flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
          onClick={() => window.open(meta.url, "_blank")}
          type="button"
        >
          <ExternalLink className="size-3" />
        </button>
      </div>

      {/* Browser viewport — mock content */}
      <div className="relative min-h-[180px] bg-white dark:bg-zinc-900 flex flex-col">
        {/* Loading skeleton or completed state */}
        {isRunning && (
          <div className="flex flex-col gap-3 p-4">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-lg">{meta.favicon}</span>
              <span className="text-[11px] font-semibold text-zinc-800 dark:text-zinc-200 truncate">
                {meta.label}
              </span>
            </div>
            {/* Skeleton rows */}
            <div className="animate-pulse space-y-2">
              <div className="h-2.5 bg-zinc-200 dark:bg-zinc-700 rounded w-3/4" />
              <div className="h-2.5 bg-zinc-200 dark:bg-zinc-700 rounded w-full" />
              <div className="h-2.5 bg-zinc-200 dark:bg-zinc-700 rounded w-5/6" />
              <div className="h-2.5 bg-zinc-200 dark:bg-zinc-700 rounded w-2/3" />
            </div>
            <div className="mt-1 animate-pulse space-y-2">
              <div className="h-2 bg-zinc-100 dark:bg-zinc-800 rounded w-full" />
              <div className="h-2 bg-zinc-100 dark:bg-zinc-800 rounded w-4/5" />
              <div className="h-2 bg-zinc-100 dark:bg-zinc-800 rounded w-full" />
            </div>
          </div>
        )}

        {isCompleted && (
          <div className="flex flex-col items-center justify-center gap-3 p-6 h-full">
            <div className="flex size-10 items-center justify-center rounded-full bg-emerald-500/10">
              <CheckCircle2 className="size-5 text-emerald-500" />
            </div>
            <div className="text-center">
              <p className="text-[12px] font-semibold text-zinc-800 dark:text-zinc-200">
                {meta.label}
              </p>
              <p className="text-[10px] text-zinc-500 mt-0.5">
                {agent.queryCompleted} · {sessionElapsed(session)}
              </p>
            </div>
            <div className="mt-1 w-full space-y-1.5">
              <div className="h-2 bg-zinc-100 dark:bg-zinc-800 rounded w-full" />
              <div className="h-2 bg-zinc-100 dark:bg-zinc-800 rounded w-4/5" />
              <div className="h-2 bg-zinc-100 dark:bg-zinc-800 rounded w-3/4" />
            </div>
          </div>
        )}

        {session.status === "idle" && (
          <div className="flex flex-col items-center justify-center gap-2 p-6 h-full">
            <Globe className="size-6 text-muted-foreground/30" />
            <p className="text-[10px] text-muted-foreground/50">
              {agent.waitingStart}
            </p>
          </div>
        )}

        {/* Agent ID badge overlaid bottom-right */}
        <div className="absolute bottom-1.5 right-2">
          <span className="text-[8px] font-mono text-zinc-300 dark:text-zinc-600 select-all">
            {session.agentId}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── TaskRow ───────────────────────────────────────────────────────────────────

function TaskRow({ task }: { task: AgentTask }) {
  return (
    <div className="flex items-center gap-2.5 py-1.5">
      <span className="shrink-0">
        {task.status === "completed" && (
          <CheckCircle2 className="size-3.5 text-emerald-500" />
        )}
        {task.status === "running" && (
          <Loader2 className="size-3.5 animate-spin text-primary" />
        )}
        {task.status === "pending" && (
          <CircleDashed className="size-3.5 text-muted-foreground/40" />
        )}
        {task.status === "error" && <X className="size-3.5 text-destructive" />}
      </span>

      <span
        className={cn(
          "flex-1 text-[12px] leading-snug truncate",
          task.status === "completed" && "text-foreground/80",
          task.status === "running" && "text-foreground font-medium",
          task.status === "pending" && "text-muted-foreground/50",
          task.status === "error" && "text-destructive"
        )}
      >
        {task.label}
      </span>

      {task.status === "completed" && task.durationMs !== undefined && (
        <span className="shrink-0 text-[10px] text-muted-foreground/60 tabular-nums">
          {formatDuration(task.durationMs)}
        </span>
      )}
    </div>
  );
}

// ── MetricBadge ────────────────────────────────────────────────────────────────

function MetricBadge({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
}) {
  return (
    <div className="flex flex-col items-center gap-0.5 rounded-xl border border-border/30 bg-muted/30 px-3 py-2 min-w-0">
      <Icon className="size-3.5 text-muted-foreground mb-0.5" />
      <span className="text-[11px] font-semibold tabular-nums text-foreground leading-none">
        {value}
      </span>
      <span className="text-[9px] text-muted-foreground/60 uppercase tracking-wider leading-none mt-0.5">
        {label}
      </span>
    </div>
  );
}

// ── SessionPanel ───────────────────────────────────────────────────────────────

function SessionPanel({ session }: { session: AgentSession }) {
  const { t } = useLanguage();
  const agent = t.panel.sidebar.agent;
  const completedTasks = session.tasks.filter(
    (t) => t.status === "completed"
  ).length;
  const totalTasks = session.tasks.length;
  const isRunning = session.status === "running";
  const isCompleted = session.status === "completed";

  return (
    <div className="flex flex-col gap-4">
      {/* ── Embedded browser ── */}
      <EmbeddedBrowser session={session} />

      {/* Status banner */}
      <div
        className={cn(
          "flex items-center gap-2 rounded-xl px-3 py-2.5 text-xs font-medium border",
          isRunning && "border-primary/20 bg-primary/5 text-primary",
          isCompleted &&
            "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
          session.status === "idle" &&
            "border-border/30 bg-muted/30 text-muted-foreground"
        )}
      >
        {isRunning && <Loader2 className="size-3.5 animate-spin shrink-0" />}
        {isCompleted && <CheckCircle2 className="size-3.5 shrink-0" />}
        {session.status === "idle" && (
          <CircleDashed className="size-3.5 shrink-0" />
        )}
        <span>
          {isRunning &&
            interpolate(agent.runningTasksDone, {
              completed: completedTasks,
              done: completedTasks === 1 ? "" : "s",
            })}
          {isCompleted &&
            interpolate(agent.completedTasks, { total: totalTasks })}
          {session.status === "idle" && agent.waitingToStart}
        </span>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-3 gap-2">
        <MetricBadge
          icon={ListChecks}
          label={agent.tasks}
          value={isRunning ? `${completedTasks}` : `${totalTasks}`}
        />
        <MetricBadge
          icon={Clock}
          label={agent.time}
          value={sessionElapsed(session)}
        />
        <MetricBadge
          icon={DollarSign}
          label={agent.cost}
          value={formatCost(session.totalCostCents)}
        />
      </div>

      {/* Progress bar
          – running   → indeterminate pulse (total is unknown)
          – completed → full solid green                         */}
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
        {isCompleted && (
          <div className="h-full w-full rounded-full bg-emerald-500 transition-all duration-700" />
        )}
        {isRunning && (
          <div className="h-full w-full rounded-full bg-primary animate-pulse" />
        )}
      </div>

      {/* Task list — grows dynamically as the agent appends new tasks */}
      <div className="flex flex-col divide-y divide-border/20">
        {session.tasks.map((task) => (
          <TaskRow key={task.id} task={task} />
        ))}
      </div>
    </div>
  );
}

// ── AgentSidebar ───────────────────────────────────────────────────────────────

export function AgentSidebar() {
  const { activeSession, allSessions, close, setActiveAgent, activeAgentId } =
    useAgentSidebar();
  const { t } = useLanguage();
  const agent = t.panel.sidebar.agent;

  return (
    <div className="flex h-full w-[400px] shrink-0 flex-col border-l border-border/40 bg-sidebar">
      {/* ── Header ── */}
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-border/40 px-4">
        <div className="flex items-center gap-2">
          <Cpu className="size-4 text-primary" />
          <span className="font-semibold text-sm">{agent.monitor}</span>
          {allSessions.length > 0 && (
            <span className="flex size-4 items-center justify-center rounded-full bg-primary/10 text-[9px] font-bold text-primary">
              {allSessions.length}
            </span>
          )}
        </div>
        <button
          aria-label={agent.close}
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          onClick={close}
          type="button"
        >
          <X className="size-4" />
        </button>
      </div>

      {/* ── Session tabs (when multiple sessions exist) ── */}
      {allSessions.length > 1 && (
        <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-border/40 p-2 no-scrollbar">
          {allSessions.map((session) => (
            <button
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors whitespace-nowrap",
                session.agentId === activeAgentId
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
              key={session.agentId}
              onClick={() => setActiveAgent(session.agentId)}
              type="button"
            >
              {session.status === "running" && (
                <Loader2 className="size-3 animate-spin" />
              )}
              {session.status === "completed" && (
                <CheckCircle2 className="size-3 text-emerald-500" />
              )}
              {session.status === "idle" && <CircleDashed className="size-3" />}
              {session.toolName}
            </button>
          ))}
        </div>
      )}

      {/* ── Content ── */}
      <div className="flex-1 overflow-y-auto px-4 py-4 no-scrollbar">
        {activeSession ? (
          <div>
            {/* Tool name header */}
            <div className="mb-4">
              <h2 className="text-base font-semibold leading-tight">
                {activeSession.toolName}
              </h2>
              {activeSession.messageId && (
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  {agent.message} ·{" "}
                  <span className="font-mono">
                    {activeSession.messageId.slice(0, 8) ||
                      activeSession.agentId.slice(0, 8)}
                    ...
                  </span>
                </p>
              )}
            </div>
            <SessionPanel session={activeSession} />
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <Cpu className="size-8 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">{agent.noSession}</p>
            <p className="text-xs text-muted-foreground/50 max-w-[18ch]">
              {agent.noSessionHint}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
