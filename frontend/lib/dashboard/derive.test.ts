import { startOfDay } from "date-fns";
import { describe, expect, it } from "vitest";
import type { AgentSession } from "@/lib/ai/tools/agent-execution";
import { buildVolumeSeries, deriveKpisFromSessions } from "./derive";

function session(overrides: Partial<AgentSession> = {}): AgentSession {
  return {
    agentId: "agent-1",
    toolName: "ConsultaArca",
    messageId: "msg-1",
    status: "completed",
    tasks: [],
    totalCostCents: 0,
    ...overrides,
  };
}

describe("deriveKpisFromSessions", () => {
  it("returns zero-state for an empty session list", () => {
    expect(deriveKpisFromSessions([])).toEqual({
      agentRuns: 0,
      browserSessions: 0,
      totalSpendCents: 0,
    });
  });

  it("counts runs and sums cost across sessions", () => {
    const sessions = [
      session({ totalCostCents: 120 }),
      session({ totalCostCents: 380 }),
    ];
    expect(deriveKpisFromSessions(sessions)).toEqual({
      agentRuns: 2,
      browserSessions: 0,
      totalSpendCents: 500,
    });
  });
});

describe("buildVolumeSeries", () => {
  const now = new Date("2026-08-07T12:00:00");

  it("returns one bucket per day for a 7d range", () => {
    const points = buildVolumeSeries([], "7d", now);
    expect(points).toHaveLength(7);
  });

  it("returns one bucket per hour for a 1d range", () => {
    const points = buildVolumeSeries([], "1d", now);
    expect(points).toHaveLength(24);
  });

  it("places a session in the bucket matching its startedAt timestamp", () => {
    const startOfToday = startOfDay(now).getTime();
    const points = buildVolumeSeries(
      [session({ startedAt: startOfToday + 1000, totalCostCents: 250 })],
      "7d",
      now
    );
    const todayBucket = points.at(-1);
    expect(todayBucket?.volume).toBe(1);
    expect(todayBucket?.spendCents).toBe(250);
  });

  it("excludes sessions without a startedAt timestamp", () => {
    const points = buildVolumeSeries(
      [session({ startedAt: undefined })],
      "7d",
      now
    );
    expect(points.every((p) => p.volume === 0)).toBe(true);
  });
});
