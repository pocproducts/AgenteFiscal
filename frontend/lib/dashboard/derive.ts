import { addDays, addHours, format, startOfDay, startOfHour } from "date-fns";
import { es } from "date-fns/locale";
import type { AgentSession } from "@/lib/ai/tools/agent-execution";
import type { DashboardKpis, DashboardRange, VolumePoint } from "./types";

/**
 * Derived from real client-local agent sessions (useAgentSidebar), not random
 * data — an empty session list correctly renders the zero-state. Browser
 * session tracking has no real hook yet (remote-browser page is static mock
 * data), so it stays at 0 until that lands.
 */
export function deriveKpisFromSessions(
  sessions: AgentSession[]
): DashboardKpis {
  return {
    agentRuns: sessions.length,
    browserSessions: 0,
    totalSpendCents: sessions.reduce(
      (sum, session) => sum + session.totalCostCents,
      0
    ),
  };
}

interface RangeBucketConfig {
  count: number;
  bucketStart: (index: number) => Date;
  bucketEnd: (index: number) => Date;
  label: (index: number) => string;
}

function bucketFor(range: DashboardRange, now: Date): RangeBucketConfig {
  switch (range) {
    case "1d": {
      const end = startOfHour(now);
      return {
        count: 24,
        bucketStart: (index) => addHours(end, index - 23),
        bucketEnd: (index) => addHours(end, index - 22),
        label: (index) =>
          format(addHours(end, index - 23), "HH:00", { locale: es }),
      };
    }
    case "7d": {
      const end = startOfDay(now);
      return {
        count: 7,
        bucketStart: (index) => addDays(end, index - 6),
        bucketEnd: (index) => addDays(end, index - 5),
        label: (index) =>
          format(addDays(end, index - 6), "dd MMM", { locale: es }),
      };
    }
    case "30d": {
      const end = startOfDay(now);
      return {
        count: 30,
        bucketStart: (index) => addDays(end, index - 29),
        bucketEnd: (index) => addDays(end, index - 28),
        label: (index) =>
          format(addDays(end, index - 29), "dd MMM", { locale: es }),
      };
    }
    default:
      throw new Error(`Unsupported dashboard range: ${range satisfies never}`);
  }
}

export function buildVolumeSeries(
  sessions: AgentSession[],
  range: DashboardRange,
  now: Date = new Date()
): VolumePoint[] {
  const bucket = bucketFor(range, now);
  const points: VolumePoint[] = [];

  for (let index = 0; index < bucket.count; index += 1) {
    const start = bucket.bucketStart(index).getTime();
    const end = bucket.bucketEnd(index).getTime();
    const inBucket = sessions.filter(
      (session) =>
        session.startedAt !== undefined &&
        session.startedAt >= start &&
        session.startedAt < end
    );

    points.push({
      label: bucket.label(index),
      timestamp: start,
      volume: inBucket.length,
      spendCents: inBucket.reduce((sum, s) => sum + s.totalCostCents, 0),
    });
  }

  return points;
}
