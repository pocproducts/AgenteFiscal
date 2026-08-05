"use client";

import {
  Check,
  Coins,
  CreditCard,
  Crown,
  Plus,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLanguage } from "@/lib/i18n";

type Dict = ReturnType<typeof useLanguage>["t"]["panel"]["pages"]["settings"];

const RECHARGE_AMOUNTS = [10, 30, 50, 100, 150, 300];

// ─── Mock usage data (30d / 7d intervals) ───
// Structure ready to be replaced by real API data.
type UsageWeek = {
  label: string;
  start: string;
  end: string;
  amount: number;
  isPartial?: boolean;
};

const USAGE_DATA: UsageWeek[] = [
  { label: "Jun 8-14", start: "2026-06-08", end: "2026-06-14", amount: 12.5 },
  { label: "Jun 15-21", start: "2026-06-15", end: "2026-06-21", amount: 28.3 },
  { label: "Jun 22-28", start: "2026-06-22", end: "2026-06-28", amount: 15.8 },
  {
    label: "Jun 29-Jul 5",
    start: "2026-06-29",
    end: "2026-07-05",
    amount: 45.2,
  },
  {
    label: "Jul 6-12",
    start: "2026-07-06",
    end: "2026-07-12",
    amount: 18.4,
    isPartial: true,
  },
];

const PLANS_META = [
  { id: "Free", price: "$0", icon: Sparkles, highlighted: false },
  { id: "Pro", price: "$29", icon: Zap, highlighted: true },
  { id: "Enterprise", price: "$99", icon: Crown, highlighted: false },
];

// ─── Usage Chart component (area chart) ───
function UsageChart({
  data,
  currentBalance,
  dict,
}: {
  data: UsageWeek[];
  currentBalance: number;
  dict: Dict;
}) {
  const totalUsed = useMemo(
    () => data.reduce((sum, d) => sum + d.amount, 0),
    [data]
  );
  const maxAmount = useMemo(
    () => Math.max(...data.map((d) => d.amount), 1),
    [data]
  );

  const W = 500;
  const H = 180;
  const PAD = { top: 8, right: 8, bottom: 24, left: 4 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;
  const pointCount = data.length;
  const stepX = pointCount > 1 ? chartW / (pointCount - 1) : chartW;

  const points = data.map((d, i) => ({
    x: PAD.left + i * stepX,
    y: PAD.top + chartH - (d.amount / maxAmount) * chartH,
    ...d,
  }));

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`)
    .join(" ");
  const areaPath = `${linePath} L${points[points.length - 1].x},${PAD.top + chartH} L${points[0].x},${PAD.top + chartH} Z`;

  const yLabels = [
    { value: 0, label: `$${maxAmount.toFixed(0)}` },
    { value: maxAmount / 2, label: `$${(maxAmount / 2).toFixed(0)}` },
    { value: maxAmount, label: "$0" },
  ];

  return (
    <div className="rounded-2xl border border-border/50 bg-card/60 p-5 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">
            {dict.billing.usage30}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-muted-foreground">
            {dict.billing.balance}{" "}
            <span className="font-semibold text-foreground">
              ${currentBalance}
            </span>
          </span>
          <span className="text-sm text-muted-foreground">
            {dict.billing.used}{" "}
            <span className="font-semibold text-foreground">
              ${totalUsed.toFixed(2)}
            </span>
          </span>
        </div>
      </div>

      {/* Chart */}
      <div className="relative">
        {/* Y-axis labels (top-to-bottom: high→low) */}
        <div className="absolute left-0 inset-y-0 flex flex-col justify-between text-[10px] text-muted-foreground/50 pointer-events-none py-[8px]">
          {yLabels.map((l) => (
            <span key={l.value}>{l.label}</span>
          ))}
        </div>

        {/* SVG */}
        <div className="ml-8">
          <svg
            className="w-full h-auto"
            preserveAspectRatio="none"
            style={{ height: H }}
            viewBox={`0 0 ${W} ${H}`}
          >
            {/* Grid lines */}
            {yLabels.map((l) => {
              const y = PAD.top + chartH - (l.value / maxAmount) * chartH;
              return (
                <line
                  className="stroke-border/20"
                  key={l.value}
                  strokeWidth="1"
                  x1={PAD.left}
                  x2={W - PAD.right}
                  y1={y}
                  y2={y}
                />
              );
            })}

            {/* Area fill */}
            <path className="fill-primary/10" d={areaPath} />

            {/* Line */}
            <path
              className="stroke-primary"
              d={linePath}
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
            />

            {/* Dots + hover tooltip targets */}
            {points.map((p) => (
              <g className="group" key={p.label}>
                {/* Invisible wider hit area for hover */}
                <rect
                  className="fill-transparent cursor-pointer"
                  height={chartH}
                  width={40}
                  x={p.x - 20}
                  y={PAD.top}
                />
                {/* Dot */}
                <circle
                  className={`fill-background stroke-primary stroke-2 transition-all duration-150 group-hover:r-[6] ${
                    p.isPartial ? "opacity-50" : ""
                  }`}
                  cx={p.x}
                  cy={p.y}
                  r="4"
                />
                {/* Tooltip */}
                <g className="pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                  <rect
                    className="fill-popover stroke-border/30"
                    height={22}
                    rx={6}
                    width={72}
                    x={p.x - 36}
                    y={p.y - 32}
                  />
                  <text
                    className="fill-popover-foreground text-[10px] font-medium"
                    textAnchor="middle"
                    x={p.x}
                    y={p.y - 17}
                  >
                    ${p.amount.toFixed(2)}
                  </text>
                </g>
              </g>
            ))}
          </svg>

          {/* X-axis labels */}
          <div className="flex justify-between mt-1">
            {data.map((d) => (
              <span
                className="text-[10px] text-muted-foreground/60"
                key={d.label}
              >
                {d.label}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function BillingSettingsPage() {
  const [customAmount, setCustomAmount] = useState("");
  const [selectedRecharge, setSelectedRecharge] = useState<number | null>(null);
  const { t } = useLanguage();
  const dict = t.panel.pages.settings;
  const currentBalance = 45;

  const validCustomAmount = (() => {
    const num = Number.parseInt(customAmount, 10);
    return !Number.isNaN(num) && num >= 100;
  })();

  const plans = PLANS_META.map((meta) => ({
    ...meta,
    definition: dict.billing.plans.find(
      (p) => (p as { name: string }).name === meta.id
    ),
  }));

  return (
    <div className="flex flex-1 flex-col h-full bg-background/50 overflow-y-auto">
      {/* Header */}
      <div className="flex flex-col border-b border-border/40">
        <div className="w-full max-w-2xl mx-auto px-6">
          <div className="flex flex-col py-8">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10">
                <CreditCard className="h-5 w-5 text-primary" />
              </div>
              <h1 className="text-lg font-semibold tracking-tight text-foreground">
                {dict.billing.title}
              </h1>
            </div>
            <p className="text-sm text-muted-foreground mt-1.5">
              {dict.billing.description}
            </p>
          </div>
        </div>

        <div className="border-t border-border/40" />
      </div>

      {/* Content */}
      <div className="flex flex-col gap-10 px-6 py-8 w-full max-w-2xl mx-auto">
        {/* ─── Usage Chart + Current Balance ─── */}
        <section>
          <UsageChart
            currentBalance={currentBalance}
            data={USAGE_DATA}
            dict={dict}
          />
        </section>

        {/* ─── Credit Recharge ─── */}
        <section>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Left: title + subtitle */}
            <div className="flex flex-col justify-center">
              <div className="flex items-center gap-2 mb-1">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
                  <Coins className="h-4 w-4 text-primary" />
                </div>
                <h2 className="text-base font-semibold tracking-tight text-foreground">
                  {dict.billing.rechargeTitle}
                </h2>
              </div>
              <p className="text-sm text-muted-foreground ml-10">
                {dict.billing.rechargeSubtitle}
              </p>
            </div>

            {/* Right: amounts grid + custom input */}
            <div>
              <div className="grid grid-cols-3 gap-2">
                {RECHARGE_AMOUNTS.map((amount) => {
                  const isSelected = selectedRecharge === amount;
                  return (
                    <button
                      className={`flex items-center justify-center h-11 rounded-xl border text-sm font-semibold transition-all ${
                        isSelected
                          ? "border-primary bg-primary/5 text-primary ring-1 ring-primary/30"
                          : "border-border/60 bg-card/50 text-foreground hover:border-border hover:bg-card"
                      }`}
                      key={amount}
                      onClick={() => {
                        setSelectedRecharge(amount);
                        setCustomAmount("");
                      }}
                      type="button"
                    >
                      ${amount}
                    </button>
                  );
                })}
              </div>

              <div className="flex items-center gap-2 mt-2">
                <div className="relative flex-1">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground font-semibold">
                    $
                  </span>
                  <Input
                    className="rounded-xl pl-7 h-11 text-sm"
                    max={100_000}
                    min={100}
                    onChange={(e) => {
                      setCustomAmount(e.target.value);
                      setSelectedRecharge(null);
                    }}
                    placeholder={dict.billing.customPlaceholder}
                    type="number"
                    value={customAmount}
                  />
                </div>
                <Button
                  className="rounded-xl h-11 px-5 font-semibold shrink-0"
                  disabled={!selectedRecharge && !validCustomAmount}
                >
                  <Plus className="h-4 w-4 mr-1.5" />
                  {dict.billing.rechargeButton}
                </Button>
              </div>
            </div>
          </div>
        </section>

        {/* ─── Subscription ─── */}
        <section>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="h-5 w-5 text-primary" />
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              {dict.billing.subscriptionTitle}
            </h2>
          </div>
          <p className="text-sm text-muted-foreground mb-5">
            {dict.billing.subscriptionSubtitle}
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {plans.map(({ id, price, icon: Icon, highlighted, definition }) => {
              return (
                <div
                  className={`relative flex flex-col rounded-2xl border overflow-hidden transition-all ${
                    highlighted
                      ? "border-primary/40 bg-card shadow-md ring-1 ring-primary/20"
                      : "border-border/50 bg-card/60 shadow-sm hover:shadow-md"
                  }`}
                  key={id}
                >
                  {/* Highlighted badge */}
                  {highlighted && (
                    <div className="absolute top-0 inset-x-0 h-1 bg-primary" />
                  )}

                  <div className="flex flex-col p-5 gap-4">
                    {/* Header */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <div
                          className={`flex h-9 w-9 items-center justify-center rounded-xl ${
                            highlighted
                              ? "bg-primary text-primary-foreground"
                              : "bg-primary/10 text-primary"
                          }`}
                        >
                          <Icon className="h-5 w-5" />
                        </div>
                        <div>
                          <p className="font-semibold text-foreground text-sm">
                            {definition?.name ?? id}
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            {definition?.description}
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Price */}
                    <div className="flex items-baseline gap-0.5">
                      <span className="text-2xl font-bold tracking-tight text-foreground">
                        {price}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {definition?.period}
                      </span>
                    </div>

                    {/* Features */}
                    <ul className="flex flex-col gap-2">
                      {definition?.features.map((feature) => (
                        <li
                          className="flex items-start gap-2 text-sm text-muted-foreground"
                          key={feature}
                        >
                          <Check className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                          <span>{feature}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* CTA */}
                  <div className="px-5 pb-5 mt-auto">
                    <Button
                      className="w-full rounded-xl font-semibold"
                      variant={highlighted ? "default" : "outline"}
                    >
                      {definition?.cta}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
