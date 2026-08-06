"use client";

import {
  Activity,
  BarChart,
  Bot,
  CheckCircle2,
  DollarSign,
  Globe,
  Hand,
  Hash,
  Layers,
  type LucideIcon,
  Radio,
  Sparkles,
  Timer,
  TrendingUp,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { AreaLineChart } from "@/components/analytics/charts/area-line";
import { BarColumnsChart } from "@/components/analytics/charts/bar-columns";
import {
  type StackedBarCategory,
  StackedBarChart,
} from "@/components/analytics/charts/stacked-bar";
import { KpiCard } from "@/components/analytics/kpi-card";
import { RangeSwitcher } from "@/components/analytics/range-switcher";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnalyticsOverview } from "@/hooks/use-analytics-overview";
import type { OverviewSnapshot, RangeKey } from "@/lib/analytics/types";
import { useLanguage } from "@/lib/i18n";

const CONSUMPTION_COLORS: Record<
  "agent" | "proxy" | "vdi" | "browser",
  string
> = {
  agent: "#f97316",
  proxy: "#3b82f6",
  vdi: "#10b981",
  browser: "#a855f7",
};

const SESSION_COLORS = { withTasks: "#3b82f6", withoutTasks: "#3f3f46" };
const TASK_COLORS = {
  success: "#10b981",
  failed: "#f43f5e",
  manual: "#f59e0b",
};
const BROWSER_COLOR = "#0ea5e9";

type OverviewDict = ReturnType<
  typeof useLanguage
>["t"]["panel"]["pages"]["analytics"]["overviewUi"];

function SectionHeading({
  icon: Icon,
  title,
}: {
  icon: LucideIcon;
  title: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10">
        <Icon className="h-4 w-4 text-primary" />
      </div>
      <h3 className="text-sm font-semibold tracking-tight text-foreground">
        {title}
      </h3>
    </div>
  );
}

function OverviewEmpty({ dict }: { dict: OverviewDict }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border/60 bg-card/40 py-20 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted/50">
        <BarChart className="h-7 w-7 text-muted-foreground/40" />
      </div>
      <div>
        <p className="text-sm font-medium text-foreground">
          {dict.empty.title}
        </p>
        <p className="mx-auto mt-1 max-w-sm text-xs text-muted-foreground">
          {dict.empty.recommendation}
        </p>
      </div>
    </div>
  );
}

function OverviewLoading() {
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton className="h-20 w-full" key={i} />
        ))}
      </div>
      <Skeleton className="h-64 w-full rounded-2xl" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton className="h-20 w-full" key={i} />
        ))}
      </div>
      <Skeleton className="h-64 w-full rounded-2xl" />
    </div>
  );
}

export function AnalyticsOverview({
  data,
  isLoading,
}: {
  data?: OverviewSnapshot | null;
  isLoading?: boolean;
}) {
  const { t, language } = useLanguage();
  const dict = t.panel.pages.analytics.overviewUi;
  const locale = language === "en" ? "en-US" : "es-AR";
  const [range, setRange] = useState<RangeKey>("30d");

  const { data: hookData, isLoading: hookIsLoading } =
    useAnalyticsOverview(range);
  const snapshot = data ?? hookData;
  const loading = isLoading ?? hookIsLoading;

  const num = (value: number) => value.toLocaleString(locale);
  const usd = (value: number) => `$${value.toFixed(2)}`;

  const isEmpty = !snapshot || snapshot.kpis.totalUsed <= 0;

  const rangeOptions = [
    { key: "24h", label: dict.ranges.h24 },
    { key: "7d", label: dict.ranges.h7d },
    { key: "30d", label: dict.ranges.h30d },
    { key: "90d", label: dict.ranges.h90d },
  ];

  const consumptionCategories: StackedBarCategory[] = [
    {
      key: "agent",
      label: dict.consumption.legendAgent,
      color: CONSUMPTION_COLORS.agent,
    },
    {
      key: "proxy",
      label: dict.consumption.legendProxy,
      color: CONSUMPTION_COLORS.proxy,
    },
    {
      key: "vdi",
      label: dict.consumption.legendVdi,
      color: CONSUMPTION_COLORS.vdi,
    },
    {
      key: "browser",
      label: dict.consumption.legendBrowser,
      color: CONSUMPTION_COLORS.browser,
    },
  ];

  const dailySuccessRate = snapshot
    ? snapshot.tasks.map((task) => {
        const total = task.success + task.failed + task.manual;
        return {
          date: task.date,
          value: total > 0 ? (task.success / total) * 100 : 0,
        };
      })
    : [];

  return (
    <div className="flex flex-col gap-6">
      {/* Header row */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-semibold tracking-tight text-foreground">
            {dict.title}
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {dict.subtitle}
          </p>
        </div>
        <RangeSwitcher
          onChange={(key) => setRange(key as RangeKey)}
          options={rangeOptions}
          value={range}
        />
      </div>

      {loading ? (
        <OverviewLoading />
      ) : isEmpty ? (
        <OverviewEmpty dict={dict} />
      ) : (
        <>
          {/* Section 1 — Consumption */}
          <section className="flex flex-col gap-3">
            <SectionHeading icon={Layers} title={dict.consumption.title} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-1">
                <KpiCard
                  icon={DollarSign}
                  iconClassName="text-foreground"
                  label={dict.consumption.totalUsed}
                  value={usd(snapshot.kpis.totalUsed)}
                />
                <KpiCard
                  icon={Bot}
                  iconClassName="text-orange-500"
                  label={dict.consumption.agentSteps}
                  value={num(snapshot.kpis.agentSteps)}
                />
                <KpiCard
                  icon={Globe}
                  iconClassName="text-blue-500"
                  label={dict.consumption.proxy}
                  sub={usd(snapshot.kpis.proxyCost)}
                  value={`${num(snapshot.kpis.proxyMb)} MB`}
                />
                <KpiCard
                  icon={Layers}
                  iconClassName="text-emerald-500"
                  label={dict.consumption.vdi}
                  value={`${num(snapshot.kpis.vdiHours)} h`}
                />
              </div>
              <StackedBarChart
                categories={consumptionCategories}
                data={snapshot.daily}
                emptyRecommendation={dict.empty.recommendation}
                emptyTitle={dict.empty.title}
                formatValue={usd}
                title={dict.consumption.chartTitle}
              />
            </div>
          </section>

          {/* Section 2 — Sessions */}
          <section className="flex flex-col gap-3">
            <SectionHeading icon={Activity} title={dict.sessions.title} />
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <KpiCard
                icon={Radio}
                iconClassName="text-blue-500"
                label={dict.sessions.total}
                value={num(snapshot.sessionKpis.total)}
              />
              <KpiCard
                icon={Hash}
                iconClassName="text-zinc-400"
                label={dict.sessions.withoutTasks}
                value={num(snapshot.sessionKpis.withoutTasks)}
              />
              <KpiCard
                icon={TrendingUp}
                iconClassName="text-violet-500"
                label={dict.sessions.avgTasks}
                value={num(snapshot.sessionKpis.avgTasksPerSession)}
              />
              <KpiCard
                icon={Timer}
                iconClassName="text-amber-500"
                label={dict.sessions.avgDuration}
                value={snapshot.sessionKpis.avgDuration}
              />
              <KpiCard
                icon={Sparkles}
                iconClassName="text-rose-500"
                label={dict.sessions.freeTier}
                value={num(snapshot.sessionKpis.freeTier)}
              />
            </div>
            <BarColumnsChart
              emptyRecommendation={dict.empty.recommendation}
              emptyTitle={dict.empty.title}
              formatValue={(value) => num(value)}
              labels={snapshot.sessions.map((session) => session.date)}
              series={[
                {
                  key: "withTasks",
                  label: dict.sessions.withTasks,
                  color: SESSION_COLORS.withTasks,
                  values: snapshot.sessions.map((session) => session.withTasks),
                },
                {
                  key: "withoutTasks",
                  label: dict.sessions.withoutTasks,
                  color: SESSION_COLORS.withoutTasks,
                  values: snapshot.sessions.map(
                    (session) => session.withoutTasks
                  ),
                },
              ]}
              title={dict.sessions.chartTitle}
            />
          </section>

          {/* Section 3 — Tasks */}
          <section className="flex flex-col gap-3">
            <SectionHeading icon={Bot} title={dict.tasks.title} />
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <KpiCard
                icon={CheckCircle2}
                iconClassName="text-emerald-500"
                label={dict.tasks.success}
                value={num(snapshot.taskKpis.success)}
              />
              <KpiCard
                icon={XCircle}
                iconClassName="text-rose-500"
                label={dict.tasks.failed}
                value={num(snapshot.taskKpis.failed)}
              />
              <KpiCard
                icon={Hand}
                iconClassName="text-amber-500"
                label={dict.tasks.manual}
                value={num(snapshot.taskKpis.manual)}
              />
              <KpiCard
                icon={TrendingUp}
                iconClassName="text-emerald-500"
                label={dict.tasks.successRate}
                value={`${snapshot.taskKpis.successRate.toFixed(1)}%`}
                valueClassName="text-emerald-500"
              />
            </div>
            <AreaLineChart
              color={TASK_COLORS.success}
              data={dailySuccessRate}
              emptyRecommendation={dict.empty.recommendation}
              emptyTitle={dict.empty.title}
              formatValue={(value) => `${value.toFixed(1)}%`}
              title={dict.tasks.chartTitle}
              yDomain={[0, 100]}
            />
          </section>

          {/* Section 4 — Browsers */}
          <section className="flex flex-col gap-3">
            <SectionHeading icon={Radio} title={dict.browsers.title} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
              <KpiCard
                icon={Radio}
                iconClassName="text-sky-500"
                label={dict.browsers.peak}
                sub={dict.browsers.concurrent}
                value={num(snapshot.browserPeak)}
              />
              <AreaLineChart
                color={BROWSER_COLOR}
                data={snapshot.browsers.map((browser) => ({
                  date: browser.date,
                  value: browser.concurrent,
                }))}
                emptyRecommendation={dict.empty.recommendation}
                emptyTitle={dict.empty.title}
                formatValue={(value) => num(value)}
                title={dict.browsers.chartTitle}
              />
            </div>
          </section>
        </>
      )}
    </div>
  );
}
