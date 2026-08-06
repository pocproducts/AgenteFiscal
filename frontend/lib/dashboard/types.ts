import type { AgentSession } from "@/lib/ai/tools/agent-execution";

export type DashboardRange = "1d" | "7d" | "30d";

export interface DashboardKpis {
  agentRuns: number;
  browserSessions: number;
  totalSpendCents: number;
}

export interface VolumePoint {
  label: string;
  timestamp: number;
  volume: number;
  spendCents: number;
}

/** Ready-state snapshot for the dashboard home view, derived from real
 * client-local agent sessions (useAgentSidebar). */
export interface DashboardHomeSnapshot {
  kpis: DashboardKpis;
  volume: VolumePoint[];
  recent: AgentSession[];
}
