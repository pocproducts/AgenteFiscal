"use client";

import { BarChart3 } from "lucide-react";
import { useMemo, useState } from "react";
import { RangeSwitcher } from "@/components/analytics/range-switcher";
import { Skeleton } from "@/components/ui/skeleton";
import { useVolume } from "@/hooks/use-volume";
import type { AgentSession } from "@/lib/ai/tools/agent-execution";
import type { DashboardRange } from "@/lib/dashboard/types";
import { cn } from "@/lib/utils";

interface VolumeChartDict {
  volumeLabel: string;
  spendLabel: string;
  emptyTitle: string;
  emptyDescription: string;
  ranges: { d1: string; d7: string; d30: string };
}

type Mode = "volume" | "spend";

export function VolumeChart({
  sessions,
  dict,
  isLoading = false,
}: {
  sessions: AgentSession[];
  dict: VolumeChartDict;
  isLoading?: boolean;
}) {
  const [range, setRange] = useState<DashboardRange>("7d");
  const [mode, setMode] = useState<Mode>("volume");

  const { data } = useVolume(range);
  const points = useMemo(() => data ?? [], [data]);

  const values = points.map((p) =>
    mode === "volume" ? p.volume : p.spendCents / 100
  );
  const maxValue = Math.max(...values, mode === "volume" ? 5 : 1);
  const isEmpty = sessions.length === 0 || values.every((v) => v === 0);

  const rangeOptions = [
    { key: "1d", label: dict.ranges.d1 },
    { key: "7d", label: dict.ranges.d7 },
    { key: "30d", label: dict.ranges.d30 },
  ];

  const W = 700;
  const H = 200;
  const PAD = { top: 8, right: 8, bottom: 24, left: 28 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;
  const stepX = points.length > 1 ? chartW / (points.length - 1) : chartW;

  const coords = points.map((p, i) => ({
    x: PAD.left + i * stepX,
    y: PAD.top + chartH - (values[i] / maxValue) * chartH,
    ...p,
  }));

  const linePath = coords
    .map((c, i) => `${i === 0 ? "M" : "L"}${c.x},${c.y}`)
    .join(" ");
  const areaPath =
    coords.length > 0
      ? `${linePath} L${coords.at(-1)?.x},${PAD.top + chartH} L${coords[0].x},${PAD.top + chartH} Z`
      : "";

  const yTicks = [0, maxValue / 2, maxValue];

  return (
    <div className="rounded-2xl border border-border/50 bg-card/60 p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-primary" />
          <div className="inline-flex items-center gap-1 rounded-xl border border-border/60 bg-card/80 p-1 text-xs">
            <button
              className={cn(
                "rounded-lg px-2.5 py-1 font-semibold transition-colors",
                mode === "volume"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
              onClick={() => setMode("volume")}
              type="button"
            >
              {dict.volumeLabel}
            </button>
            <button
              className={cn(
                "rounded-lg px-2.5 py-1 font-semibold transition-colors",
                mode === "spend"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
              onClick={() => setMode("spend")}
              type="button"
            >
              {dict.spendLabel}
            </button>
          </div>
        </div>
        <RangeSwitcher
          onChange={(k) => setRange(k as DashboardRange)}
          options={rangeOptions}
          value={range}
        />
      </div>

      {isLoading ? (
        <div className="mt-5 flex flex-col gap-4">
          <Skeleton className="h-40 w-full" />
          <div className="flex justify-between">
            <Skeleton className="h-3 w-10" />
            <Skeleton className="h-3 w-10" />
            <Skeleton className="h-3 w-10" />
            <Skeleton className="h-3 w-10" />
          </div>
        </div>
      ) : (
        <div className="relative mt-5">
          {isEmpty ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
              <p className="text-sm font-medium text-foreground">
                {dict.emptyTitle}
              </p>
              <p className="max-w-xs text-xs text-muted-foreground">
                {dict.emptyDescription}
              </p>
            </div>
          ) : (
            <>
              <div className="absolute inset-y-0 left-0 flex flex-col justify-between py-[8px] text-[10px] text-muted-foreground/60">
                {[...yTicks].reverse().map((tick) => (
                  <span key={tick}>{Math.round(tick)}</span>
                ))}
              </div>
              <div className="ml-7">
                <svg
                  className="h-auto w-full"
                  preserveAspectRatio="none"
                  style={{ height: H }}
                  viewBox={`0 0 ${W} ${H}`}
                >
                  {yTicks.map((tick) => {
                    const y = PAD.top + chartH - (tick / maxValue) * chartH;
                    return (
                      <line
                        className="stroke-border/20"
                        key={tick}
                        strokeDasharray="3 3"
                        strokeWidth="1"
                        x1={PAD.left}
                        x2={W - PAD.right}
                        y1={y}
                        y2={y}
                      />
                    );
                  })}
                  <path className="fill-primary/10" d={areaPath} />
                  <path
                    className="stroke-primary"
                    d={linePath}
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2"
                  />
                  {coords.map((c) => (
                    <circle
                      className="fill-background stroke-primary stroke-2"
                      cx={c.x}
                      cy={c.y}
                      key={c.timestamp}
                      r="3"
                    />
                  ))}
                </svg>
                <div className="mt-1 flex justify-between">
                  {points.map((p, i) => (
                    <span
                      className="text-[10px] text-muted-foreground/60"
                      key={p.timestamp}
                    >
                      {i % Math.ceil(points.length / 8 || 1) === 0
                        ? p.label
                        : ""}
                    </span>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
