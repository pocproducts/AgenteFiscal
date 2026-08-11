"use client";

import { Layers } from "lucide-react";
import { type MouseEvent, useRef, useState } from "react";
import type {
  ConsumptionCategory,
  DayConsumption,
} from "@/lib/analytics/types";
import { cn } from "@/lib/utils";

export interface StackedBarCategory {
  key: Exclude<ConsumptionCategory, "total">;
  label: string;
  color: string;
}

export interface StackedBarProps {
  data: DayConsumption[];
  categories: StackedBarCategory[];
  title: string;
  formatValue: (value: number) => string;
  emptyTitle: string;
  emptyRecommendation: string;
  className?: string;
}

const W = 760;
const H = 240;
const PAD = { top: 12, right: 12, bottom: 24, left: 46 };

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function niceTicks(max: number, target: number, baseStep?: number): number[] {
  if (max <= 0) {
    return [0];
  }
  let step: number;
  if (baseStep === undefined) {
    const raw = max / target;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const norm = raw / magnitude;
    step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * magnitude;
  } else {
    step = baseStep;
  }
  const ticks: number[] = [];
  for (let value = 0; value <= max + step * 0.001; value += step) {
    ticks.push(round2(value));
  }
  return ticks;
}

export function StackedBarChart({
  data,
  categories,
  title,
  formatValue,
  emptyTitle,
  emptyRecommendation,
  className,
}: StackedBarProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{
    index: number;
    x: number;
    y: number;
  } | null>(null);

  const maxTotal = Math.max(...data.map((day) => day.total), 0);
  // Every $0.50 on small scales (per spec), auto-nicestep once consumption grows.
  const ticks = niceTicks(
    maxTotal,
    6,
    maxTotal > 0 && maxTotal <= 5 ? 0.5 : undefined
  );
  const scaleMax = Math.max(...ticks, maxTotal);

  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;
  const slot = data.length > 0 ? chartW / data.length : chartW;
  const barWidth = Math.max(6, Math.min(30, slot * 0.62));

  const yFor = (value: number) =>
    PAD.top + chartH - (value / Math.max(scaleMax, 0.0001)) * chartH;

  const bars = data.map((day, index) => {
    let cursor = PAD.top + chartH;
    const segments = categories.map((category) => {
      const value = day[category.key];
      const height = (value / scaleMax) * chartH;
      cursor -= height;
      return {
        ...category,
        value,
        x: PAD.left + index * slot + (slot - barWidth) / 2,
        y: cursor,
        height,
      };
    });
    return { date: day.date, index, segments };
  });

  const hovered = hover ? bars[hover.index] : null;
  const labelStep = Math.max(1, Math.ceil(data.length / 12));
  const canRender = data.length > 0 && scaleMax > 0;

  const updateHover = (event: MouseEvent<SVGRectElement>, index: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    setHover({
      index,
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    });
  };

  return (
    <div
      className={cn(
        "rounded-2xl border border-border/50 bg-card/60 p-5 shadow-sm",
        className
      )}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Layers className="h-4 w-4 text-primary" />
          </div>
          <h3 className="text-sm font-semibold tracking-tight text-foreground">
            {title}
          </h3>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {categories.map((category) => (
            <span
              className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
              key={category.key}
            >
              <span
                className="h-2 w-2 rounded-[3px]"
                style={{ backgroundColor: category.color }}
              />
              {category.label}
            </span>
          ))}
        </div>
      </div>

      {canRender ? (
        <div className="relative" ref={containerRef}>
          <svg
            className="h-auto w-full"
            style={{ height: H }}
            viewBox={`0 0 ${W} ${H}`}
          >
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  className="stroke-border/20"
                  strokeWidth="1"
                  x1={PAD.left}
                  x2={W - PAD.right}
                  y1={yFor(tick)}
                  y2={yFor(tick)}
                />
                <text
                  className="fill-muted-foreground/60 font-mono text-[10px]"
                  textAnchor="end"
                  x={PAD.left - 6}
                  y={yFor(tick) + 3}
                >
                  {formatValue(tick)}
                </text>
              </g>
            ))}
            {bars.map((bar) => (
              <g key={bar.date}>
                {bar.segments.map((segment) => (
                  <rect
                    fill={segment.color}
                    height={Math.max(0, segment.height)}
                    key={segment.key}
                    opacity={
                      hover === null || hover.index === bar.index ? 0.95 : 0.45
                    }
                    width={barWidth}
                    x={segment.x}
                    y={segment.y}
                  />
                ))}
                {/* biome-ignore lint/a11y/noStaticElementInteractions: transparent decorative SVG hover hit overlay; chart data is already visible via the rendered segment marks, so this overlay adds mouse-only tooltip enhancement. */}
                <rect
                  fill="transparent"
                  focusable="false"
                  height={chartH}
                  onMouseEnter={(event) => updateHover(event, bar.index)}
                  onMouseLeave={() => setHover(null)}
                  onMouseMove={(event) => updateHover(event, bar.index)}
                  width={slot}
                  x={PAD.left + bar.index * slot}
                  y={PAD.top}
                />
              </g>
            ))}
            {data.map((day, index) =>
              index % labelStep === 0 || index === data.length - 1 ? (
                <text
                  className="fill-muted-foreground/60 text-[10px]"
                  key={day.date}
                  textAnchor="middle"
                  x={PAD.left + index * slot + slot / 2}
                  y={H - 6}
                >
                  {day.date}
                </text>
              ) : null
            )}
          </svg>

          {hover && hovered && containerRef.current ? (
            <div
              className="pointer-events-none absolute z-10 w-[190px] rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 shadow-float"
              style={{
                left: Math.min(
                  hover.x + 12,
                  containerRef.current.clientWidth - 198
                ),
                top: Math.max(4, hover.y - 96),
              }}
            >
              <p className="text-xs font-semibold text-zinc-100">
                {hovered.date}
              </p>
              <div className="mt-1.5 flex flex-col gap-1">
                {hovered.segments.map((segment) => (
                  <div
                    className="flex items-center justify-between gap-2"
                    key={segment.key}
                  >
                    <span className="flex items-center gap-1.5 text-[11px] text-zinc-300">
                      <span
                        className="h-2 w-2 rounded-[3px]"
                        style={{ backgroundColor: segment.color }}
                      />
                      {segment.label}
                    </span>
                    <span className="font-mono text-[11px] text-zinc-100">
                      {formatValue(segment.value)}
                    </span>
                  </div>
                ))}
                <div className="mt-1 flex items-center justify-between border-t border-zinc-700 pt-1">
                  <span className="text-[11px] font-semibold text-zinc-300">
                    Total
                  </span>
                  <span className="font-mono text-[11px] font-semibold text-zinc-100">
                    {formatValue(data[hovered.index].total)}
                  </span>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="flex h-56 flex-col items-center justify-center gap-2 text-center">
          <Layers className="h-6 w-6 text-muted-foreground/40" />
          <p className="text-sm font-medium text-foreground">{emptyTitle}</p>
          <p className="max-w-xs text-xs text-muted-foreground">
            {emptyRecommendation}
          </p>
        </div>
      )}
    </div>
  );
}
