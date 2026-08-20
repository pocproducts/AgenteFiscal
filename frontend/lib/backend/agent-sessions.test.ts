import { describe, expect, it } from "vitest";

import { buildSubtasksForTool } from "@/lib/ai/tools/agent-execution";
import type { AgentSessionSnapshot } from "@/lib/ai/tools/agent-execution";
import {
  mapAgentSessionRow,
  toAgentSessionSnapshots,
  type BackendAgentSessionRow,
} from "./agent-sessions";

// ── AST-3: consultaarca template length ─────────────────────────────────────
// The engine template (backend/ai/tools/agent-execution.ts) must carry the 7
// canonical "Acciones" labels, mirrored from domain/session_tasks.py. The BFF
// and page render a "N tasks · last label" summary straight from this shape.

const CONSULTAARCA_LABELS = [
  "Authenticating with ARCA gateway",
  "Fetching taxpayer profile",
  "Retrieving tax obligations",
  "Validating response schema",
  "Consulting payment obligations",
  "Cross-checking due dates",
  "Formatting output",
];

describe("consultaarca subtask template (AST-3)", () => {
  it("builds exactly the 7 canonical tasks in order", () => {
    const tasks = buildSubtasksForTool("consultaarca");
    expect(tasks).toHaveLength(7);
    expect(tasks.map((t) => t.label)).toEqual(CONSULTAARCA_LABELS);
    expect(tasks.map((t) => t.id)).toEqual([
      "task-0",
      "task-1",
      "task-2",
      "task-3",
      "task-4",
      "task-5",
      "task-6",
    ]);
  });

  it("every built task starts pending (live monitor repaints them)", () => {
    for (const task of buildSubtasksForTool("consultaarca")) {
      expect(task.status).toBe("pending");
    }
  });
});

// ── AST-6: persisted row → UI mapping ───────────────────────────────────────
// The BFF (app/(chat)/api/agent-sessions and /api/messages routes) projects the
// backend snake_case rows into the camelCase page contract and the
// AgentSessionSnapshot hydrate contract. These tests pin that projection so a
// backend key rename can never silently break the chat monitor or the page.

const ROW: BackendAgentSessionRow = {
  id: "row-1",
  tool: "consultaarca",
  message_id: "msg-9",
  conversation_id: "conv-1",
  profile_id: null,
  tenant_id: "tenant-1",
  user_id: "user-1",
  session_id: null,
  status: "completed",
  tasks: [
    { task: "task-0", label: "Fetching taxpayer profile", status: "completed" },
    { task: "task-1", label: "Formatting output", status: "completed" },
  ],
  cost_cents: 123,
  started_at: "2026-08-18T12:00:00Z",
  completed_at: "2026-08-18T12:00:05Z",
  created_at: "2026-08-18T12:00:00Z",
};

describe("mapAgentSessionRow (snake_case → camelCase)", () => {
  it("projects every backend key to the UI contract", () => {
    const row = mapAgentSessionRow(ROW);
    expect(row).toEqual({
      id: "row-1",
      tool: "consultaarca",
      messageId: "msg-9",
      conversationId: "conv-1",
      profileId: null,
      tenantId: "tenant-1",
      userId: "user-1",
      sessionId: null,
      status: "completed",
      tasks: ROW.tasks,
      costCents: 123,
      startedAt: "2026-08-18T12:00:00Z",
      completedAt: "2026-08-18T12:00:05Z",
      createdAt: "2026-08-18T12:00:00Z",
    });
  });

  it("keeps null optionals null (AST-3 engine rows have NULL ids)", () => {
    const row = mapAgentSessionRow({ ...ROW, profile_id: null, session_id: null });
    expect(row.profileId).toBeNull();
    expect(row.sessionId).toBeNull();
  });
});

describe("toAgentSessionSnapshots (hydrate contract, AST-6)", () => {
  it("maps each row to an AgentSessionSnapshot with row id as agentId", () => {
    const snapshots = toAgentSessionSnapshots([ROW]);
    expect(snapshots).toHaveLength(1);
    const snap = snapshots[0];
    expect(snap.agentId).toBe("row-1");
    expect(snap.toolKey).toBe("consultaarca");
    expect(snap.toolName).toBe("ConsultaArca");
    expect(snap.totalCostCents).toBe(123);
    expect(snap.startedAt).toBe(new Date("2026-08-18T12:00:00Z").getTime());
    expect(snap.completedAt).toBe(new Date("2026-08-18T12:00:05Z").getTime());
    expect(snap.tasks.map((t) => t.label)).toEqual([
      "Fetching taxpayer profile",
      "Formatting output",
    ]);
  });

  it("persists error tasks as error and treats everything else as completed", () => {
    const rows: BackendAgentSessionRow[] = [
      { ...ROW, tasks: [{ task: "t0", label: "Fail", status: "error" }] },
      { ...ROW, tasks: [{ task: "t0", label: "Done", status: "success" }] },
      { ...ROW, tasks: [{ task: "t0", label: "Ongoing", status: "running" }] },
    ];
    const snapshots = toAgentSessionSnapshots(rows);
    expect(snapshots[0].tasks[0].status).toBe("error");
    expect(snapshots[1].tasks[0].status).toBe("completed");
    expect(snapshots[2].tasks[0].status).toBe("completed");
  });

  it("assigns each snapshot a distinct agentId (dedupe against live sessions)", () => {
    const ids = toAgentSessionSnapshots([ROW, { ...ROW, id: "row-2" }]).map(
      (s) => s.agentId
    );
    expect(ids).toEqual(["row-1", "row-2"]);
  });
});

// Keep the snapshot type in the emitted artifact check: the projector must
// satisfy the exact hydrate contract, not a look-alike.
const _shapeCheck: AgentSessionSnapshot[] = toAgentSessionSnapshots([ROW]);
void _shapeCheck;