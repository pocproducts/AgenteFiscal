# Proposal: UI Backend-Readiness

## Intent
Panel views render invented data (PRNG analytics snapshots, hardcoded billing tokens/plan, KPIs implying fake costs) with no correspondence to the future backend. Define it now: typed per-domain snapshot contracts, hooks returning { data, isLoading, error }, empty/loading states per view, so modules wire to real endpoints incrementally.

## Goals
- Typed per-domain data-access layer (DTOs + SWR hooks)
- Empty + loading state in every target view
- Delete invented fixtures; keep dashboard derivation (rename-only)
- Remove fake auth delay; useProfiles signature stable; UsageChart empty guard (NaN fix)

## Non-goals
- No backend, no real HTTP endpoints, no API wiring
- Fiscal agent pipeline untouched: backend/ai/tools/*, composer→chat stream→useAgentSidebar persistence, sidebar-history
- No browser-session tracking; browserSessions stays documented 0
- No chart-primitive changes (demilitarized array props kept)

## Capabilities (all new: openspec/specs/ is empty)
- analytics-data-access: useAnalyticsOverview(range) + useGateway(range, isCustom); delete mock.ts + panel toggles
- billing-data-access: useBilling + isLoading/error; INITIAL_BILLING_STATE→fetcher; UsageChart guard
- dashboard-data-access: mock.ts→derive.ts rename; useDashboardHome() + useVolume(range)
- remote-browser-data-access: RemoteBrowserRow DTO + useRemoteBrowsers(); delete DUMMY_BROWSERS, wire empty branch
- profiles-data-access: async auth, no fake delay; Profile.id + signature stable

## Approach
Mirror useBilling: useSWR(key, fetcher|default, {fallbackData}) → { data, isLoading, error, mutate }; hooks accept a default fetcher so today's fallbackData path still renders. Reuse DTOs from lib/analytics/types.ts, lib/billing/types.ts, lib/dashboard/types.ts: zero type changes. Rename dashboard/mock.ts→derive.ts (bodies untouched); delete analytics/mock.ts + its two panel imports. Add data/loading props to analytics-overview, llm-gateway-panel, dashboard-view, volume-chart, recent-activity-table; drop simulateEmpty/isCustom toggles from llm-gateway-panel. Add settings.billing.* loading/empty i18n keys; skeletons via existing Skeleton.

## Affected Areas
- frontend/lib/analytics/mock.ts: removed (only deletion)
- frontend/lib/dashboard/mock.ts: renamed → derive.ts
- frontend/hooks/use-billing.ts, use-profiles.ts: +loading/error; state→fetcher; async auth; same signatures
- frontend/hooks/use-{analytics-overview,gateway,dashboard-home,volume,remote-browsers}.ts: new hooks
- frontend/lib/remote-browser/types.ts: new DTO
- frontend/components/analytics/{analytics-overview,llm-gateway-panel}.tsx: types-only imports, data/loading, drop toggles
- frontend/components/dashboard/{dashboard-view,volume-chart,recent-activity-table}.tsx: data/loading props
- frontend/app/(chat)/settings/{billing,profiles}/page.tsx: drop USAGE_DATA + chart guard; real async auth
- frontend/app/(chat)/remote-browser/page.tsx: delete DUMMY_BROWSERS, wire empty branch
- frontend/i18n/dictionary.ts: loading/empty keys

Untouched: backend/ai/tools/*, use-agent-sidebar.ts, sidebar-history.tsx, agent-sessions pages, multimodal-input.tsx, chart primitives, kpi-row.tsx, billing widgets, all lib/*/types.ts.

## Risks
- Med: RangeKey/RangeSwitcher.onChange: keep 24h / 7d / 30d / 90d; add custom only with real backend
- Med: Profile.id/setProfileAuth consumers: keep signature + type unchanged
- Med: useBilling optimistic mutate(data=>…,false): preserve + revalidate; topbar offline intact
- Low: type imports after analytics/mock.ts deletion: types-only; 2 consumers
- Low: e2e mock-number assertions: verified none

## Rollback Plan
Revert the change commit; fixtures restore from git history (no generated files). Hook + component changes revert as one atomic commit; no feature flag needed (no backend wiring yet).

## Dependencies
Exploration map in this change folder (§1 imports, §3 contracts): authoritative.

## Success Criteria
- [ ] pnpm build + pnpm test pass; zero hits for getOverview, getGateway, INITIAL_BILLING_STATE, USAGE_DATA, DUMMY_BROWSERS, deterministicRandom in frontend/
- [ ] analytics/mock.ts deleted; dashboard/mock.ts→derive.ts bodies identical
- [ ] Every view: skeleton on isLoading, empty state on null/[] (UsageChart no NaN)
- [ ] useBilling/useProfiles signatures unchanged; backend/ai/tools/* untouched
