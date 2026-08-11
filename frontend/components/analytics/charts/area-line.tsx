"use client";

import { Activity } from "lucide-react";
import { useId, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface AreaLinePoint {
  date: string;
  value: number;
}

export interface AreaLineProps {
  data: AreaLinePoint[];
  color: string;
  title: string;
  formatValue: (value: number) => string;
  yDomain?: [number, number];
  emptyTitle: string;
  emptyRecommendation: string;
  className?: string;
}

const W = 760;
const H = 220;
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

function smoothPath(points: Array<{ x: number; y: number }>): string {
  const first = points.at(0);
  if (!first) {
    return "";
  }
  if (points.length === 1) {
    return `M${first.x},${first.y}`;
  }
  let d = `M${first.x},${first.y}`;
  for (let index = 1; index < points.length; index += 1) {
    const prev = points[index - 1];
    const curr = points[index];
    const midX = (prev.x + curr.x) / 2;
    d += ` C${midX},${prev.y} ${midX},${curr.y} ${curr.x},${curr.y}`;
  }
  return d;
}

export function AreaLineChart({
  data,
  color,
  title,
  formatValue,
  yDomain,
  emptyTitle,
  emptyRecommendation,
  className,
}: AreaLineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const gradientId = useId().replace(/:/g, "");

  const maxData = Math.max(0, ...data.map((point) => point.value));
  const scaleMin = yDomain ? yDomain[0] : 0;
  const scaleMax = yDomain ? yDomain[1] : maxData * 1.15 || 1;
  const ticks = niceTicks(scaleMax, 5);

  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;
  const slot = data.length > 0 ? chartW / data.length : chartW;

  const yFor = (value: number) =>
    PAD.top + (1 - (value - scaleMin) / (scaleMax - scaleMin)) * chartH;

  const points = data.map((point, index) => ({
    x: PAD.left + index * slot + slot / 2,
    y: Math.min(PAD.top + chartH, Math.max(PAD.top, yFor(point.value))),
    ...point,
  }));

  const linePath = smoothPath(points);
  const baseline = yFor(scaleMin);
  const lastPoint = points.at(-1);
  const areaPath =
    points.length > 1
      ? lastPoint && linePath
        ? `${linePath} L${lastPoint.x},${baseline} L${points[0].x},${baseline} Z`
        : ""
      : "";

  const labelStep = Math.max(1, Math.ceil(data.length / 12));
  const showDots = data.length <= 16;
  const canRender = data.length > 0 && maxData > 0;

  const updateHover = (index: number) => {
    setHover(index);
  };

  return (
    <div
      className={cn(
        "rounded-2xl border border-border/50 bg-card/60 p-5 shadow-sm",
        className
      )}
    >
      <div className="mb-4 flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
          <Activity className="h-4 w-4 text-primary" />
        </div>
        <h3 className="text-sm font-semibold tracking-tight text-foreground">
          {title}
        </h3>
      </div>

      {canRender ? (
        <div className="relative" ref={containerRef}>
          <svg
            className="h-auto w-full"
            style={{ height: H }}
            viewBox={`0 0 ${W} ${H}`}
          >
            <defs>
              <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity="0.28" />
                <stop offset="100%" stopColor={color} stopOpacity="0.02" />
              </linearGradient>
            </defs>
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  className="stroke-border/20"
                  strokeWidth="1"
                  x1={PAD.left}
                  x2={W - PAD.right}
                  y1={yFor(Math.max(scaleMin, tick))}
                  y2={yFor(Math.max(scaleMin, tick))}
                />
                <text
                  className="fill-muted-foreground/60 font-mono text-[10px]"
                  textAnchor="end"
                  x={PAD.left - 6}
                  y={yFor(Math.max(scaleMin, tick)) + 3}
                >
                  {formatValue(tick)}
                </text>
              </g>
            ))}
            {areaPath ? (
              <path d={areaPath} fill={`url(#${gradientId})`} stroke="none" />
            ) : null}
            <path
              className="fill-none"
              d={linePath}
              stroke={color}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
            />
            {points.map((point, index) => (
              <circle
                cx={point.x}
                cy={point.y}
                fill="var(--card)"
                key={point.date}
                opacity={showDots || hover === index ? 1 : 0}
                r={hover === index ? 4.5 : 3.5}
                stroke={color}
                strokeWidth="2"
              />
            ))}
            {points.map((point, index) => (
              // biome-ignore lint/a11y/noStaticElementInteractions: transparent decorative SVG hover hit-target; chart data is already visible via the marks and text labels, so this overlay adds mouse-only tooltip enhancement.
              <rect
                fill="transparent"
                focusable="false"
                height={chartH}
                key={`hit-${point.date}`}
                onMouseEnter={() => updateHover(index)}
                onMouseLeave={() => setHover(null)}
                onMouseMove={() => updateHover(index)}
                width={slot}
                x={point.x - slot / 2}
                y={PAD.top}
              />
            ))}
            {data.map((point, index) =>
              index % labelStep === 0 || index === data.length - 1 ? (
                <text
                  className="fill-muted-foreground/60 text-[10px]"
                  key={point.date}
                  textAnchor="middle"
                  x={PAD.left + index * slot + slot / 2}
                  y={H - 6}
                >
                  {point.date}
                </text>
              ) : null
            )}
          </svg>

          {hover !== null && points[hover] ? (
            <div
              className="pointer-events-none absolute z-10 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 shadow-float"
              style={{
                left: Math.min(
                  points[hover].x + 12,
                  (containerRef.current?.clientWidth ?? 0) - 150
                ),
                top: Math.max(4, points[hover].y - 42),
              }}
            >
              <p className="text-xs font-semibold text-zinc-100">
                {points[hover].date}
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-zinc-100">
                {formatValue(points[hover].value)}
              </p>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="flex h-48 flex-col items-center justify-center gap-2 text-center">
          <Activity className="h-6 w-6 text-muted-foreground/40" />
          <p className="text-sm font-medium text-foreground">{emptyTitle}</p>
          <p className="max-w-xs text-xs text-muted-foreground">
            {emptyRecommendation}
          </p>
        </div>
      )}
    </div>
  );
}
