export type RangeKey = "24h" | "7d" | "30d" | "90d";

export type ConsumptionCategory = "agent" | "proxy" | "vdi" | "browser";

export interface DayConsumption {
  date: string;
  total: number;
  agent: number;
  proxy: number;
  vdi: number;
  browser: number;
}

export interface OverviewKpis {
  totalUsed: number;
  agentSteps: number;
  proxyMb: number;
  proxyCost: number;
  vdiHours: number;
}

export interface SessionPoint {
  date: string;
  withTasks: number;
  withoutTasks: number;
}

export interface SessionKpis {
  total: number;
  withoutTasks: number;
  avgTasksPerSession: number;
  avgDuration: string;
  freeTier: number;
}

export interface TaskPoint {
  date: string;
  success: number;
  failed: number;
  manual: number;
}

export interface TaskKpis {
  success: number;
  failed: number;
  manual: number;
  successRate: number;
}

export interface BrowserPoint {
  date: string;
  concurrent: number;
}

export interface GatewayKpis {
  requests: number;
  tokens: number;
  cachedTokens: number;
  peakTpm: number;
  cost: number;
}

export interface GatewayPoint {
  date: string;
  tokens: number;
  requests: number;
  cost: number;
  peakTpm: number;
  cachedTokens: number;
}

export interface ModelBreakdownRow {
  model: string;
  provider: string;
  requests: number;
  avgLatencyMs: number;
  inputTokens: number;
  outputTokens: number;
  cost: number;
}

export interface ByokProvider {
  id: string;
  label: string;
  description: string;
  encrypted: boolean;
}

export interface OverviewSnapshot {
  range: RangeKey;
  kpis: OverviewKpis;
  daily: DayConsumption[];
  sessions: SessionPoint[];
  sessionKpis: SessionKpis;
  tasks: TaskPoint[];
  taskKpis: TaskKpis;
  browsers: BrowserPoint[];
  browserPeak: number;
}

export interface GatewaySnapshot {
  kpis: GatewayKpis;
  points: GatewayPoint[];
  models: ModelBreakdownRow[];
  byok: ByokProvider[];
}
