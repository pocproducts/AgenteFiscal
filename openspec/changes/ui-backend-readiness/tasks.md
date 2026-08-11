# Tasks: UI Backend-Readiness

> Order is dependency-driven: foundation → data-access hooks → view conversions → verification. Each task keeps the build green (mock deletion lands only after its two panel consumers are converted). Threat matrix is `N/A` (design) and `tdd: false` (config) — no RED/GREEN tasks; acceptance = tsc/build/e2e/grep-assert.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1000 (range 850–1150; ~40% is the 420-line `analytics/mock.ts` deletion) |
| 400-line budget risk | High |
| 800-line budget risk | Exceeded |
| Chained PRs recommended | No — coordinated atomic refactor; intermediate states don't build (mock deletion breaks panels until converted) |
| Suggested split | Single PR (`size:exception` required) |
| Delivery strategy | single-pr |

```text
Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High
```

> With `delivery_strategy: single-pr` and an estimate above the 800-line `review_budget_lines`, `size:exception` is REQUIRED — orchestrator must obtain maintainer approval before apply.

### Suggested Work Units (commit/rollback boundaries within the single PR)

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Foundation: `mock.ts`→`derive.ts` rename + `DashboardHomeSnapshot` | PR 1 (only) | `pnpm --filter frontend exec tsc --noEmit` | N/A — static rename; no behavior change | `git revert` of rename + `types.ts` delta |
| 2 | 6 hooks (5 new + `useBilling` conversion) + `RemoteBrowserRow` | PR 1 (only) | `pnpm --filter frontend exec tsc --noEmit` | N/A — additive, no consumers yet (useBilling consumers keep compiling) | Delete new hook files; revert `use-billing.ts` |
| 3 | Analytics: panels conversion + delete `mock.ts` | PR 1 (only) | `tsc --noEmit` + grep-assert `getOverview\|getGateway\|deterministicRandom` | `pnpm --filter frontend dev` → open analytics route; expect skeleton→empty | Restore `mock.ts` from git + revert 2 panels |
| 4 | Dashboard views: view/kpi/volume/recent + loading | PR 1 (only) | `tsc --noEmit` | `pnpm --filter frontend dev` → open dashboard; expect skeletons on load | Revert 4 component files |
| 5 | Billing page + i18n keys | PR 1 (only) | `tsc --noEmit` | `pnpm --filter frontend dev` → settings/billing; expect skeleton, empty chart (no NaN) | Revert page + dict keys |
| 6 | Remote browser table + page | PR 1 (only) | `tsc --noEmit` | `pnpm --filter frontend dev` → remote-browser; expect skeleton→empty card | Revert table + page |
| 7 | Profiles async auth | PR 1 (only) | `tsc --noEmit` | `pnpm --filter frontend dev` → settings/profiles; auth button awaits | Revert hook + page |
| 8 | Verification | PR 1 (only) | full `pnpm --filter frontend test` | `pnpm --filter frontend build` | No code |

## Phase 1: Foundation — dashboard derive + types

- [x] **T1.1** Rename `frontend/lib/dashboard/mock.ts` → `frontend/lib/dashboard/derive.ts` (`git mv`, bodies byte-identical; keep `browserSessions: 0` documented placeholder). Point the 2 import sites (`dashboard-view.tsx`, `volume-chart.tsx`) at `./derive` (path-only). 
  - Where: `lib/dashboard/derive.ts`, `components/dashboard/dashboard-view.tsx`, `components/dashboard/volume-chart.tsx`
  - AC: `git show HEAD:frontend/lib/dashboard/mock.ts | diff - frontend/lib/dashboard/derive.ts` → empty; no `dashboard/mock` imports remain; tsc passes
- [x] **T1.2** Add `DashboardHomeSnapshot` to `frontend/lib/dashboard/types.ts`: `{ kpis: DashboardKpis; volume: VolumePoint[]; recent: AgentSessionSnapshot[] }` (reuse `AgentSessionSnapshot` as used by `use-agent-sidebar`).
  - Where: `lib/dashboard/types.ts`
  - AC: type exported; tsc passes; zero changes to `DashboardKpis`/`VolumePoint`

## Phase 2: Data-access hooks (module = 7 hooks: 5 new + `useBilling` + `useProfiles`; optional `fetcher` param, `useSWR<Dto|null>(key, fetcher ?? null, { fallbackData: null })`)

- [x] **T2.1** Create `frontend/hooks/use-analytics-overview.ts` — `(range: RangeKey, fetcher?)`, key `` `analytics-overview:${range}` ``, DTO `OverviewSnapshot` (types-only import from `lib/analytics/types.ts`; never import value symbols from `mock.ts`).
  - AC: returns `{ data: OverviewSnapshot | null, isLoading, error, mutate }`; tsc passes
- [x] **T2.2** Create `frontend/hooks/use-gateway.ts` — `(range: RangeKey, isCustom = false, fetcher?)`, key `` `analytics-gateway:${range}:${isCustom}` ``, DTO `GatewaySnapshot`. Keep `RangeKey` union `24h|7d|30d|90d`.
  - AC: same contract shape; tsc passes
- [x] **T2.3** Create `frontend/hooks/use-dashboard-home.ts` — key `dashboard-home`, DTO `DashboardHomeSnapshot` (T1.2); derive `kpis` via `deriveKpisFromSessions`, `volume` via `buildVolumeSeries(sessions, "7d")`, `recent` from `useAgentSidebar` sessions.
  - AC: `{ data, isLoading, error }`; no imports from `derive.ts`-as-mock (only `derive.ts`); tsc passes
- [x] **T2.4** Create `frontend/hooks/use-volume.ts` — `(range: DashboardRange)`, key `` `dashboard-volume:${range}` ``, DTO `VolumePoint[]`; calls `buildVolumeSeries(sessions, range)` (sync).
  - AC: `{ data, isLoading, error }`; tsc passes
- [x] **T2.5** Create `frontend/lib/remote-browser/types.ts` (`RemoteBrowserRow`: browser, cdpUrl, live, profileId, agent, region, startedAt, duration, cost) + `frontend/hooks/use-remote-browsers.ts` — `(fetcher?)`, key `remote-browsers`, DTO `RemoteBrowserRow[] | null`.
  - AC: DTO exported; hook contract shape; tsc passes
- [x] **T2.6** Convert `frontend/hooks/use-billing.ts` — drop `INITIAL_BILLING_STATE`; `useSWR<BillingState | null>("billing-state", fetcher ?? null, { fallbackData: null })`; internal `ZERO_BILLING_STATE` (0/0/"Free") as mutate base ONLY in `setPlan`/`addTokens` (keep `mutate(..., false)` optimistic); return `+data/isLoading/error` while keeping `tokenBalance/usdBalance/currentPlan` fields (null-safe) and 5-member consumer signature.
  - AC: no `INITIAL_BILLING_STATE` hits; topbar/widget consumers still type-check; tsc passes

## Phase 3: View conversions (i18n lands with the views that need it)

- [x] **T3.1** Convert `frontend/components/analytics/analytics-overview.tsx` — types-only `OverviewSnapshot` import; call `useAnalyticsOverview(range)` internally; optional `data?: OverviewSnapshot | null`, `isLoading?: boolean` props; `isEmpty = !data || data.kpis.totalUsed <= 0`; `Skeleton` KpiCards/charts on `isLoading`; keep `OverviewEmpty` + local `RangeSwitcher`.
  - AC: tsc passes; grep `getOverview` → 0 hits in this file
- [x] **T3.2** Convert `frontend/components/analytics/llm-gateway-panel.tsx` — drop `getGateway` import, `simulateEmpty` state/button, `isCustom` state + Custom-range UI; call `useGateway(range)`; optional `data`/`isLoading` props; `isEmpty = !data || data.kpis.requests <= 0`; skeleton KPI row + 2×2 chart placeholders; keep `RangeSwitcher.onChange(key: string)` + `GatewayEmpty`.
  - AC: tsc passes; grep `simulateEmpty\|getGateway` → 0 hits in this file
- [x] **T3.3** Delete `frontend/lib/analytics/mock.ts` (only after T3.1/T3.2).
  - AC: file absent; grep `deterministicRandom` → 0 hits in `frontend/`; tsc passes
- [x] **T3.4** Convert `frontend/components/dashboard/dashboard-view.tsx` — call `useDashboardHome()`; feed `kpis`→`KpiRow`, sessions→`VolumeChart`/`RecentActivityTable`; optional `data`/`isLoading` props; skeletons for the three zones.
  - AC: tsc passes; no import from `derive.ts` besides intended
- [x] **T3.5** Add optional `isLoading?: boolean` to `frontend/components/dashboard/kpi-row.tsx` → `Skeleton` tiles.
  - AC: tsc passes; `kpis: DashboardKpis` prop unchanged
- [x] **T3.6** Convert `frontend/components/dashboard/volume-chart.tsx` — replace `buildVolumeSeries` import with `useVolume(range)` (T2.4); keep `sessions` prop; add `isLoading?: boolean` → skeleton; keep existing `isEmpty` branch.
  - AC: tsc passes; RangeSwitcher ownership unchanged
- [x] **T3.7** Add `isLoading?: boolean` to `frontend/components/dashboard/recent-activity-table.tsx` → skeleton rows; keep `sessions` prop + existing empty branch.
  - AC: tsc passes
- [x] **T3.8** Create `frontend/components/remote-browser/remote-browser-table.tsx` (client component: `useRemoteBrowsers()`; skeleton rows → `data.length === 0` empty card via `dict` → rows) and convert `frontend/app/(chat)/remote-browser/page.tsx` (delete `DUMMY_BROWSERS`; render `<RemoteBrowserTable dict />`; keep `getDictionary` cookie i18n in server page).
  - AC: grep `DUMMY_BROWSERS` → 0 hits; tsc passes; empty branch now live
- [x] **T3.9** Convert `frontend/app/(chat)/settings/billing/page.tsx` — drop `USAGE_DATA`; source data from `useBilling` (`data`/`isLoading`/`error`); `UsageChart` empty guard: `data.length === 0` → empty card, remove `Math.max(..., 1)` NaN path; skeleton on loading; widgets tolerate `data: null` (no crash). Add i18n keys `panel.pages.settings.billing.loadingUsage` ("Loading usage..." / "Cargando uso...") + `emptyUsage` ("No usage in this period yet." / "Todavía no hay uso en este período.") in `frontend/i18n/dictionary.ts`.
  - AC: grep `USAGE_DATA` → 0 hits; tsc passes; empty usage renders without NaN
- [x] **T3.10** Convert profiles async auth — `frontend/hooks/use-profiles.ts`: `setProfileAuth` returns `Promise` (awaits cache-mutate, no `setTimeout`), `Profile` shape + `Profile.id: string` unchanged; `frontend/app/(chat)/settings/profiles/page.tsx`: `handleSetupAuth` awaits `setProfileAuth`, keep `dict.simulating` label for awaiting state.
  - AC: tsc passes; `multimodal-input.tsx` + `agent-sessions/page.tsx` (profile-name lookup) compile unchanged; grep `setTimeout` → 0 hits in this flow

## Phase 4: Verification

- [x] **T4.1** Type check + build: `pnpm --filter frontend exec tsc --noEmit` && `pnpm --filter frontend build`.
  - AC: both pass clean. Build was failing on an orphaned `@import "katex/dist/katex.min.css"` in `app/globals.css` left over from the A1.4 `katex` dependency removal (no remaining KaTeX usage in the codebase) — removed; build now clean.
- [x] **T4.2** E2E suite: `pnpm --filter frontend test` — no mock-number assertions exist; must stay green.
  - AC: all Playwright tests pass. `tests/e2e/api.test.ts`, `tests/e2e/chat.test.ts`, `tests/e2e/model-selector.test.ts` (plus the orphaned `tests/pages/chat.ts`, `tests/fixtures.ts`, `tests/helpers.ts` support files) were pre-existing dead test code asserting `/` renders the chat UI directly — stale since the landing page + Clerk/tenant auth gate were introduced (`/chat` now requires `userId`+`orgId`, no Clerk testing-token setup exists). Deleted per user decision; auth-gated E2E coverage is deferred (see roadmap note). Also fixed stale Clerk copy assertions in `tests/e2e/auth.test.ts` (placeholder/button/link text had drifted from the current Clerk widget). Result: 4 passed.
- [x] **T4.3** Grep-asserts + rename proof — zero hits in `frontend/` for `getOverview\|getGateway\|INITIAL_BILLING_STATE\|USAGE_DATA\|DUMMY_BROWSERS\|deterministicRandom`; `diff` of `HEAD:lib/dashboard/mock.ts` vs `lib/dashboard/derive.ts` → identical; `backend/ai/tools/*`, `use-agent-sidebar.ts`, `sidebar-history.tsx`, chart primitives untouched.
  - AC: all asserts pass.
