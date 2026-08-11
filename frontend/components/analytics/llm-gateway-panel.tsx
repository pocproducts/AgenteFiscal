"use client";

import {
  ArrowLeftRight,
  Bot,
  Cpu,
  DollarSign,
  Hash,
  KeyRound,
  Lock,
  type LucideIcon,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { AreaLineChart } from "@/components/analytics/charts/area-line";
import { BarColumnsChart } from "@/components/analytics/charts/bar-columns";
import { KpiCard } from "@/components/analytics/kpi-card";
import { RangeSwitcher } from "@/components/analytics/range-switcher";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useGateway } from "@/hooks/use-gateway";
import type {
  ByokProvider,
  GatewaySnapshot,
  ModelBreakdownRow,
  RangeKey,
} from "@/lib/analytics/types";
import { useLanguage } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const HISTOGRAM_COLORS = {
  tokens: "#3b82f6",
  requests: "#10b981",
  cost: "#f59e0b",
  peakTpm: "#a855f7",
};

const PROVIDER_ICONS: Record<string, LucideIcon> = {
  google: Sparkles,
  anthropic: Bot,
  openai: Cpu,
};

type GatewayDict = ReturnType<
  typeof useLanguage
>["t"]["panel"]["pages"]["analytics"]["llmGatewayUi"];

function formatTokens(value: number): string {
  if (value >= 1e9) {
    return `${(value / 1e9).toFixed(2)}B`;
  }
  if (value >= 1e6) {
    return `${(value / 1e6).toFixed(1)}M`;
  }
  if (value >= 1e3) {
    return `${Math.round(value / 1e3)}K`;
  }
  return `${Math.round(value)}`;
}

function GatewayEmpty({ dict }: { dict: GatewayDict }) {
  const { language } = useLanguage();
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/30 dark:bg-zinc-950/20 py-16 text-center shadow-[0_0_15px_rgba(16,185,129,0.02)]">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-zinc-900 border border-zinc-800 shadow-[0_0_10px_rgba(16,185,129,0.15)]">
        <svg
          className="h-8 w-8 text-[#10b981]"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          viewBox="0 0 24 24"
        >
          <circle
            className="fill-[#10b981]/15 animate-pulse"
            cx="12"
            cy="12"
            r="3"
          />
          <ellipse
            className="opacity-65"
            cx="12"
            cy="12"
            rx="9"
            ry="3.5"
            transform="rotate(45 12 12)"
          />
          <ellipse
            className="opacity-65"
            cx="12"
            cy="12"
            rx="9"
            ry="3.5"
            transform="rotate(-45 12 12)"
          />
        </svg>
      </div>
      <div>
        <p className="text-sm font-bold tracking-tight text-foreground">
          {dict.empty.title}
        </p>
        <p className="mx-auto mt-1 max-w-sm text-xs text-muted-foreground leading-relaxed">
          {dict.empty.recommendation}
        </p>
      </div>
      <Button
        className="mt-1 rounded-xl border-zinc-800 bg-zinc-900/80 text-xs font-semibold hover:bg-zinc-800 hover:text-foreground"
        onClick={() =>
          toast.info(
            language === "es"
              ? "Para generar tráfico, envía una consulta al chatbot en la barra lateral."
              : "To generate traffic, send a query to the chatbot in the sidebar."
          )
        }
        size="sm"
        variant="outline"
      >
        Ejecutar Consulta Demo / Test Route
      </Button>
    </div>
  );
}

function ModelTable({
  models,
  dict,
  locale,
}: {
  models: ModelBreakdownRow[];
  dict: GatewayDict;
  locale: string;
}) {
  const num = (value: number) => value.toLocaleString(locale);
  const headerClassName =
    "whitespace-nowrap px-5 py-2.5 text-left uppercase tracking-wider text-[11px] font-bold text-muted-foreground";
  const cellClassName = "px-5 py-3 font-mono text-muted-foreground text-right";

  return (
    <div className="overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/50 dark:bg-zinc-950/40 shadow-sm">
      <div className="flex items-center gap-2 border-b border-zinc-800/80 px-5 py-4">
        <Cpu className="h-4 w-4 text-[#10b981]" />
        <h3 className="text-sm font-semibold tracking-tight text-foreground">
          {dict.byModel.title}
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-zinc-800/80 bg-zinc-950/40">
              <th className={headerClassName}>{dict.byModel.model}</th>
              <th className={headerClassName}>{dict.byModel.provider}</th>
              <th className={cn(headerClassName, "text-right")}>
                {dict.byModel.requests}
              </th>
              <th className={cn(headerClassName, "text-right")}>
                {dict.byModel.latency}
              </th>
              <th className={cn(headerClassName, "text-right")}>
                {dict.byModel.tokensInOut}
              </th>
              <th className={cn(headerClassName, "text-right")}>
                {dict.byModel.cost}
              </th>
            </tr>
          </thead>
          <tbody>
            {models.map((row) => (
              <tr
                className="border-t border-zinc-800/50 transition-colors hover:bg-zinc-900/40"
                key={row.model}
              >
                <td className="px-5 py-3 font-medium text-foreground">
                  {row.model}
                </td>
                <td className="px-5 py-3 text-muted-foreground">
                  {row.provider}
                </td>
                <td className={cellClassName}>{num(row.requests)}</td>
                <td className={cellClassName}>{num(row.avgLatencyMs)} ms</td>
                <td className={cellClassName}>
                  {formatTokens(row.inputTokens)} /{" "}
                  {formatTokens(row.outputTokens)}
                </td>
                <td className="px-5 py-3 text-right font-mono font-semibold text-foreground">
                  ${row.cost.toFixed(4)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function LlmGatewayPanel({
  data,
  isLoading,
}: {
  data?: GatewaySnapshot | null;
  isLoading?: boolean;
}) {
  const { t, language } = useLanguage();
  const dict = t.panel.pages.analytics.llmGatewayUi;
  const locale = language === "en" ? "en-US" : "es-AR";

  const [range, setRange] = useState<RangeKey>("30d");
  const [activeProvider, setActiveProvider] = useState<ByokProvider | null>(
    null
  );
  const [apiKey, setApiKey] = useState("");

  const { data: hookData, isLoading: hookIsLoading } = useGateway(range);
  const snapshot = data ?? hookData;
  const loading = isLoading ?? hookIsLoading;

  const isEmpty = !snapshot || snapshot.kpis.requests <= 0;
  const num = (value: number) => value.toLocaleString(locale);

  const kpis = snapshot?.kpis;

  const rangeOptions = [
    { key: "24h", label: dict.ranges.h24 },
    { key: "7d", label: dict.ranges.h7d },
    { key: "30d", label: dict.ranges.h30d },
    { key: "90d", label: dict.ranges.h90d },
  ];

  const handleSaveKey = (event: FormEvent) => {
    event.preventDefault();
    toast.success(dict.byok.saved);
    setActiveProvider(null);
    setApiKey("");
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header row: status + range switcher */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="inline-flex self-start items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-[#10b981] shadow-[0_0_12px_rgba(16,185,129,0.15)] transition-all">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
            <span>{dict.status.online}</span>
          </div>
        </div>
        <RangeSwitcher
          onChange={(key) => setRange(key as RangeKey)}
          options={rangeOptions}
          value={range}
        />
      </div>

      {/* Row 1 — KPIs */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {loading || !kpis ? (
          [0, 1, 2, 3].map((n) => (
            <Skeleton className="h-24 w-full rounded-2xl" key={n} />
          ))
        ) : (
          <>
            <KpiCard
              icon={Zap}
              iconClassName="text-blue-500 bg-blue-500/10"
              label={dict.kpis.requests}
              value={num(kpis.requests)}
            />
            <KpiCard
              icon={Hash}
              iconClassName="text-violet-500 bg-violet-500/10"
              label={dict.kpis.tokens}
              sub={`${dict.kpis.tokensCache}: ${formatTokens(kpis.cachedTokens)}`}
              value={formatTokens(kpis.tokens)}
            />
            <KpiCard
              icon={TrendingUp}
              iconClassName="text-[#10b981] bg-[#10b981]/10"
              label={dict.kpis.peakTpm}
              value={num(kpis.peakTpm)}
            />
            <KpiCard
              icon={DollarSign}
              iconClassName="text-amber-500 bg-amber-500/10"
              label={dict.kpis.cost}
              value={`$${kpis.cost.toFixed(4)}`}
            />
          </>
        )}
      </div>

      {/* Row 2 — 2x2 charts */}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((n) => (
            <Skeleton className="h-56 w-full rounded-2xl" key={n} />
          ))}
        </div>
      ) : isEmpty ? (
        <GatewayEmpty dict={dict} />
      ) : snapshot ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <BarColumnsChart
            emptyRecommendation={dict.empty.recommendation}
            emptyTitle={dict.empty.title}
            formatValue={formatTokens}
            labels={snapshot.points.map((point) => point.date)}
            series={[
              {
                key: "tokens",
                label: dict.charts.tokens,
                color: HISTOGRAM_COLORS.tokens,
                values: snapshot.points.map((point) => point.tokens),
              },
            ]}
            title={dict.charts.tokens}
          />
          <BarColumnsChart
            emptyRecommendation={dict.empty.recommendation}
            emptyTitle={dict.empty.title}
            formatValue={(value) => num(value)}
            labels={snapshot.points.map((point) => point.date)}
            series={[
              {
                key: "requests",
                label: dict.charts.requests,
                color: HISTOGRAM_COLORS.requests,
                values: snapshot.points.map((point) => point.requests),
              },
            ]}
            title={dict.charts.requests}
          />
          <AreaLineChart
            color={HISTOGRAM_COLORS.cost}
            data={snapshot.points.map((point) => ({
              date: point.date,
              value: point.cost,
            }))}
            emptyRecommendation={dict.empty.recommendation}
            emptyTitle={dict.empty.title}
            formatValue={(value) => `$${value.toFixed(2)}`}
            title={dict.charts.cost}
          />
          <AreaLineChart
            color={HISTOGRAM_COLORS.peakTpm}
            data={snapshot.points.map((point) => ({
              date: point.date,
              value: point.peakTpm,
            }))}
            emptyRecommendation={dict.empty.recommendation}
            emptyTitle={dict.empty.title}
            formatValue={formatTokens}
            title={dict.charts.peakTpm}
          />
        </div>
      ) : null}

      {/* By model table */}
      {snapshot ? (
        <ModelTable dict={dict} locale={locale} models={snapshot.models} />
      ) : null}

      {/* BYOK */}
      {snapshot ? (
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/50 dark:bg-zinc-950/40 p-5 shadow-sm">
          <div className="mb-1 flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-[#10b981]" />
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              {dict.byok.title}
            </h3>
          </div>
          <p className="mb-4 text-xs text-muted-foreground">
            {dict.byok.subtitle}
          </p>
          <div className="flex flex-col divide-y divide-zinc-800 border-y border-zinc-800">
            {snapshot.byok.map((provider) => {
              const ProviderIcon = PROVIDER_ICONS[provider.id] ?? Bot;
              return (
                <div
                  className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center sm:justify-between"
                  key={provider.id}
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-900 border border-zinc-800/80">
                      <ProviderIcon className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {provider.label}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {provider.description}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 pl-12 sm:pl-0">
                    {provider.encrypted ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.08)]">
                        <ShieldCheck className="h-3.5 w-3.5" />
                        {dict.byok.encryptedVault}
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full border border-zinc-850 bg-zinc-900/60 px-2.5 py-1 text-[11px] font-semibold text-muted-foreground">
                        {dict.byok.notConfigured}
                      </span>
                    )}
                    <Button
                      className="rounded-lg border-zinc-700 hover:bg-zinc-800 hover:text-foreground"
                      onClick={() => {
                        setActiveProvider(provider);
                        setApiKey("");
                      }}
                      size="sm"
                      variant="outline"
                    >
                      {provider.encrypted
                        ? dict.byok.manage
                        : dict.byok.configure}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {/* Routing / failover */}
      <div className="flex items-start gap-3 rounded-2xl border border-zinc-800 bg-zinc-900/50 dark:bg-zinc-950/40 p-4 shadow-sm hover:shadow-[0_0_12px_rgba(16,185,129,0.06)] hover:border-emerald-500/30 transition-all duration-300">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-900 border border-zinc-800 text-[#10b981] shadow-[0_0_8px_rgba(16,185,129,0.08)]">
          <ArrowLeftRight className="h-4 w-4" />
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">
            {dict.routing.title}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">
            {dict.routing.failover}
          </p>
        </div>
      </div>

      {/* BYOK API key dialog */}
      <Dialog
        onOpenChange={(open) => {
          if (!open) {
            setActiveProvider(null);
          }
        }}
        open={activeProvider !== null}
      >
        <DialogContent className="max-w-md border-zinc-800 bg-zinc-900 text-foreground">
          <form onSubmit={handleSaveKey}>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-foreground">
                <KeyRound className="h-5 w-5 text-[#10b981]" />
                {activeProvider?.label ?? dict.byok.title}
              </DialogTitle>
              <DialogDescription className="text-muted-foreground">
                {dict.byok.subtitle}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <div className="space-y-1.5">
                <Label
                  className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                  htmlFor="byok-apikey"
                >
                  {dict.byok.keyLabel}
                </Label>
                <Input
                  autoFocus
                  className="rounded-xl font-mono border-zinc-800 bg-zinc-950/45 focus:border-[#10b981]/50 focus:ring-[#10b981]/20"
                  id="byok-apikey"
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={dict.byok.keyPlaceholder}
                  type="password"
                  value={apiKey}
                />
              </div>
              <div className="flex items-start gap-2 rounded-lg border border-zinc-800/80 bg-zinc-950/40 px-3 py-2.5 text-xs text-muted-foreground">
                <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#10b981]" />
                <span>{dict.byok.vaultNote}</span>
              </div>
            </div>
            <DialogFooter className="mt-3">
              <Button
                className="rounded-xl border-zinc-800 hover:bg-zinc-800"
                onClick={() => setActiveProvider(null)}
                type="button"
                variant="outline"
              >
                {dict.byok.cancel}
              </Button>
              <Button
                className="rounded-xl bg-[#10b981] hover:bg-[#0d9488] text-zinc-950 font-bold shadow-[0_0_10px_rgba(16,185,129,0.3)]"
                type="submit"
              >
                {dict.byok.save}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
