"use client";

import { BarChart } from "lucide-react";
import { type MouseEvent, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface BarColumnSeries {
  key: string;
  label: string;
  color: string;
  values: number[];
}

export interface BarColumnsProps {
  series: BarColumnSeries[];
  labels: string[];
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

function niceTicks(max: number, target: number): number[] {
  if (max <= 0) {
    return [0];
  }
  const raw = max / target;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / magnitude;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * magnitude;
  const ticks: number[] = [];
  for (let value = 0; value <= max + step * 0.001; value += step) {
    ticks.push(round2(value));
  }
  return ticks;
}

export function BarColumnsChart({
  series,
  labels,
  title,
  formatValue,
  emptyTitle,
  emptyRecommendation,
  className,
}: BarColumnsProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{
    index: number;
    x: number;
    y: number;
  } | null>(null);

  const maxValue = Math.max(0, ...series.flatMap((s) => s.values));
  const ticks = niceTicks(maxValue, 5);
  const scaleMax = Math.max(...ticks, maxValue);

  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;
  const slot = labels.length > 0 ? chartW / labels.length : chartW;
  const groupWidth = Math.min(54, slot * 0.72);
  const barWidth = groupWidth / Math.max(series.length, 1);

  const yFor = (value: number) =>
    PAD.top + chartH - (value / Math.max(scaleMax, 0.0001)) * chartH;

  const groups = labels.map((label, index) => ({
    label,
    index,
    columns: series.map((s, position) => {
      const value = s.values[index] ?? 0;
      const height = (value / scaleMax) * chartH;
      return {
        key: s.key,
        label: s.label,
        color: s.color,
        value,
        x:
          PAD.left +
          index * slot +
          (slot - groupWidth) / 2 +
          position * barWidth,
        y: PAD.top + chartH - height,
        height,
      };
    }),
  }));

  const hovered = hover ? groups[hover.index] : null;
  const labelStep = Math.max(1, Math.ceil(labels.length / 12));
  const canRender = labels.length > 0 && scaleMax > 0;
  const showLegend = series.length > 1;

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
            <BarChart className="h-4 w-4 text-primary" />
          </div>
          <h3 className="text-sm font-semibold tracking-tight text-foreground">
            {title}
          </h3>
        </div>
        {showLegend ? (
          <div className="flex flex-wrap items-center gap-3">
            {series.map((s) => (
              <span
                className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
                key={s.key}
              >
                <span
                  className="h-2 w-2 rounded-[3px]"
                  style={{ backgroundColor: s.color }}
                />
                {s.label}
              </span>
            ))}
          </div>
        ) : null}
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
            {groups.map((group) => (
              <g key={group.label}>
                {group.columns.map((column) => (
                  <rect
                    fill={column.color}
                    height={Math.max(0, column.height)}
                    key={column.key}
                    opacity={
                      hover === null || hover.index === group.index
                        ? 0.95
                        : 0.45
                    }
                    width={barWidth}
                    x={column.x}
                    y={column.y}
                  />
                ))}
                {/* biome-ignore lint/a11y/noStaticElementInteractions: transparent decorative SVG hover hit overlay; chart data is already visible via the rendered column marks, so this overlay adds mouse-only tooltip enhancement. */}
                <rect
                  fill="transparent"
                  focusable="false"
                  height={chartH}
                  onMouseEnter={(event) => updateHover(event, group.index)}
                  onMouseLeave={() => setHover(null)}
                  onMouseMove={(event) => updateHover(event, group.index)}
                  width={slot}
                  x={PAD.left + group.index * slot}
                  y={PAD.top}
                />
              </g>
            ))}
            {labels.map((label, index) =>
              index % labelStep === 0 || index === labels.length - 1 ? (
                <text
                  className="fill-muted-foreground/60 text-[10px]"
                  key={label}
                  textAnchor="middle"
                  x={PAD.left + index * slot + slot / 2}
                  y={H - 6}
                >
                  {label}
                </text>
              ) : null
            )}
          </svg>

          {hover && hovered && containerRef.current ? (
            <div
              className="pointer-events-none absolute z-10 w-[160px] rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 shadow-float"
              style={{
                left: Math.min(
                  hover.x + 12,
                  containerRef.current.clientWidth - 168
                ),
                top: Math.max(4, hover.y - 60),
              }}
            >
              <p className="text-xs font-semibold text-zinc-100">
                {hovered.label}
              </p>
              <div className="mt-1.5 flex flex-col gap-1">
                {hovered.columns.map((column) => (
                  <div
                    className="flex items-center justify-between gap-2"
                    key={column.key}
                  >
                    <span className="flex items-center gap-1.5 text-[11px] text-zinc-300">
                      <span
                        className="h-2 w-2 rounded-[3px]"
                        style={{ backgroundColor: column.color }}
                      />
                      {column.label}
                    </span>
                    <span className="font-mono text-[11px] text-zinc-100">
                      {formatValue(column.value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="flex h-56 flex-col items-center justify-center gap-2 text-center">
          <BarChart className="h-6 w-6 text-muted-foreground/40" />
          <p className="text-sm font-medium text-foreground">{emptyTitle}</p>
          <p className="max-w-xs text-xs text-muted-foreground">
            {emptyRecommendation}
          </p>
        </div>
      )}
    </div>
  );
}
