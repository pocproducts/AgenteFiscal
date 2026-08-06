import { ArrowRight, Clock, Hash, ListChecks, Tag } from "lucide-react";
import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import type { AgentSession } from "@/lib/ai/tools/agent-execution";

interface RecentActivityDict {
  title: string;
  viewAll: string;
  status: string;
  id: string;
  type: string;
  task: string;
  started: string;
  duration: string;
  empty: string;
  running: string;
}

function getLastTaskLabel(
  tasks: AgentSession["tasks"],
  fallback: string
): string {
  if (!tasks || tasks.length === 0) {
    return fallback;
  }
  const running = tasks.find((t) => t.status === "running");
  if (running) {
    return running.label;
  }
  const completed = [...tasks].reverse().find((t) => t.status === "completed");
  return completed ? completed.label : tasks[0].label;
}

export function RecentActivityTable({
  sessions,
  dict,
  isLoading = false,
}: {
  sessions: AgentSession[];
  dict: RecentActivityDict;
  isLoading?: boolean;
}) {
  const recent = [...sessions]
    .sort((a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0))
    .slice(0, 5);

  return (
    <div className="rounded-2xl border border-border/50 bg-card/60 shadow-sm overflow-hidden">
      <div className="flex items-center justify-between border-b border-border/40 px-5 py-4">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">
          {dict.title}
        </h3>
        <Link
          className="flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          href="/agent-sessions"
        >
          {dict.viewAll}
          <ArrowRight className="size-3.5" />
        </Link>
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-3 p-5">
          {[0, 1, 2, 3].map((n) => (
            <Skeleton className="h-10 w-full" key={n} />
          ))}
        </div>
      ) : recent.length === 0 ? (
        <div className="p-10 text-center text-sm italic text-muted-foreground">
          {dict.empty}
        </div>
      ) : (
        <table className="w-full text-left text-sm whitespace-nowrap">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-5 py-3 font-medium">{dict.status}</th>
              <th className="px-5 py-3 font-medium">
                <div className="flex items-center gap-1.5">
                  <Hash className="size-3.5" /> {dict.id}
                </div>
              </th>
              <th className="px-5 py-3 font-medium">
                <div className="flex items-center gap-1.5">
                  <Tag className="size-3.5" /> {dict.type}
                </div>
              </th>
              <th className="px-5 py-3 font-medium">
                <div className="flex items-center gap-1.5">
                  <ListChecks className="size-3.5" /> {dict.task}
                </div>
              </th>
              <th className="px-5 py-3 font-medium">
                <div className="flex items-center gap-1.5">
                  <Clock className="size-3.5" /> {dict.started}
                </div>
              </th>
              <th className="px-5 py-3 font-medium">{dict.duration}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/40">
            {recent.map((s) => {
              const duration =
                s.startedAt && s.completedAt
                  ? `${((s.completedAt - s.startedAt) / 1000).toFixed(1)}s`
                  : s.startedAt
                    ? dict.running
                    : "—";

              return (
                <tr
                  className="hover:bg-muted/10 transition-colors"
                  key={s.agentId}
                >
                  <td className="px-5 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                        s.status === "completed"
                          ? "bg-emerald-500/10 text-emerald-600"
                          : s.status === "running"
                            ? "bg-amber-500/10 text-amber-600"
                            : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {s.status}
                    </span>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-muted-foreground">
                    {s.agentId.slice(0, 4)}...{s.agentId.slice(-4)}
                  </td>
                  <td className="px-5 py-3 font-medium text-foreground">
                    {s.toolName}
                  </td>
                  <td className="px-5 py-3 text-xs text-muted-foreground">
                    {getLastTaskLabel(s.tasks, "—")}
                  </td>
                  <td className="px-5 py-3 text-xs text-muted-foreground">
                    {s.startedAt ? new Date(s.startedAt).toLocaleString() : "—"}
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-muted-foreground">
                    {duration}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
