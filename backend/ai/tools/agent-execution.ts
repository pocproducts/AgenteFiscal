// Domain: Agent Execution Model
// Each fiscal tool invocation is modeled as an AgentSession — identified by a
// stable, unique ID (agentId). In the future this will map 1:1 to a backend task.

export type TaskStatus = "pending" | "running" | "completed" | "error";

export interface AgentTask {
  id: string;
  label: string;
  status: TaskStatus;
  /** elapsed ms when the task completed */
  durationMs?: number;
  /** mock cost in USD cents */
  costCents?: number;
}

export type AgentSessionStatus = "idle" | "running" | "completed" | "error";

export interface AgentSession {
  /** Stable unique ID for this agent / embedded browser instance */
  agentId: string;
  /** Human-readable tool name */
  toolName: string;
  /** The Execution Profile ID connected to this session */
  profileId?: string;
  /** The chat message this session belongs to */
  messageId: string;
  status: AgentSessionStatus;
  tasks: AgentTask[];
  /** Wall-clock start time (ms since epoch) */
  startedAt?: number;
  /** Wall-clock completion time */
  completedAt?: number;
  /** Sum of task costs */
  totalCostCents: number;
}

// ─── Sub-task templates per fiscal tool ───────────────────────────────────────

const SUBTASK_TEMPLATES: Record<string, string[]> = {
  consultaarca: [
    "Authenticating with ARCA gateway",
    "Fetching taxpayer profile",
    "Retrieving tax obligations",
    "Validating response schema",
    "Formatting output",
  ],
  sistemaregistral: [
    "Authenticating with Registro Registral",
    "Querying entity legal form",
    "Fetching registered activities",
    "Retrieving fiscal address",
    "Formatting output",
  ],
  misfacilidades: [
    "Connecting to Mis Facilidades",
    "Fetching active payment plans",
    "Computing compliance percentage",
    "Formatting output",
  ],
  deudavencimientos: [
    "Connecting to Debt & Deadlines API",
    "Fetching overdue debts",
    "Fetching pending obligations",
    "Checking judicial execution flag",
    "Formatting output",
  ],
  rentascordoba: [
    "Authenticating with Rentas Córdoba",
    "Fetching IIBB registration",
    "Retrieving activity rates",
    "Fetching last DDJJ",
    "Formatting output",
  ],
  calendariovencimientosarca: [
    "Authenticating with ARCA calendar",
    "Fetching upcoming deadlines",
    "Sorting by priority",
    "Formatting output",
  ],
};

const DEFAULT_SUBTASKS = ["Initializing", "Processing", "Completing"];

export function buildSubtasksForTool(toolKey: string): AgentTask[] {
  const labels = SUBTASK_TEMPLATES[toolKey] ?? DEFAULT_SUBTASKS;
  return labels.map((label, i) => ({
    id: `task-${i}`,
    label,
    status: "pending",
  }));
}

export function generateAgentId(): string {
  // In the future this will be a backend-generated UUID.
  // For now: timestamp + random to guarantee uniqueness per session.
  return `agent-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}
