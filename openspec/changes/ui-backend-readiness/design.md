# Design: UI Backend-Readiness

## Technical Approach
One typed data-access layer mirrors `useBilling`'s SWR pattern: `useSWR<Dto>(key, fetcher | null, { fallbackData: null })` → `{ data, isLoading, error, mutate }`. Every hook accepts an optional `fetcher` (default `undefined`, passed as `null` to SWR) so today's path returns `null` (views render empty states) and a real fetcher slots in per module with zero view changes. DTOs reuse existing `lib/*/types.ts` — zero type changes. `lib/analytics/mock.ts` is deleted; `lib/dashboard/mock.ts` is renamed to `derive.ts` (bodies byte-identical). Views gain `data`/`isLoading` props + skeleton/empty rendering via existing `components/ui/skeleton.tsx` and i18n keys. Fiscal-agent pipeline untouched.

## Architecture Decisions
| # | Decision | Alternatives | Rationale |
|---|---|---|---|
| D1 | Optional `fetcher` param on every hook, default `undefined` → SWR `null` fetcher, `fallbackData: null` | Hardcode mocks inside hooks | Mirrors `useBilling`; renders empty today, future fetcher slots in with no view changes |
| D2 | `useBilling` keeps 5-member signature, adds `data` + `isLoading` + `error`; `INITIAL_BILLING_STATE` → internal `ZERO_BILLING_STATE` (0/0/"Free") used only as mutate base, never rendered | Nullable scalar fields | Preserves consumer types; `data: BillingState \| null` lets widgets render `—`/skeleton |
| D3 | Analytics/gateway components keep local range state and call hooks internally; optional `data`/`isLoading` props override for tests/future | Move hook up to server pages | Pages are async server components — cannot call client hooks |
| D4 | `volume-chart`/`recent-activity-table` keep `sessions` prop (real client state, per-range bucketing) + add `isLoading`; volume via `useVolume(range)` inside chart | Pre-computed `data` prop, range state moved to parent | Chart owns its RangeSwitcher; avoids UX-breaking refactor |
| D5 | Remote-browser table extracted to a client component calling `useRemoteBrowsers()`; server page renders header + `<RemoteBrowserTable dict />` | Make page client | Server page keeps `getDictionary` cookie i18n |
| D6 | `setProfileAuth` becomes `async` (Promise), no fake `setTimeout`; page awaits it | Keep sync | Real endpoint slots in later; signature stable for 3 consumers |

## Data Flow
```
useAgentSidebar (sessions) ─→ useDashboardHome ─→ { kpis, volume, recent } ─→ DashboardView → KpiRow / VolumeChart / RecentActivityTable
                               useVolume(range) ─→ buildVolumeSeries (derive.ts) ─→ VolumeChart
useAnalyticsOverview(range) ─→ OverviewSnapshot | null ─→ AnalyticsOverview → empty | charts
useGateway(range) ───────────→ GatewaySnapshot | null ─→ LlmGatewayPanel → empty | charts
useBilling() ────────────────→ { data, tokenBalance, usdBalance, currentPlan, mutate } ─→ widgets + billing page
useRemoteBrowsers() ─────────→ RemoteBrowserRow[] | null ─→ RemoteBrowserTable → skeleton | empty | rows
useProfiles() ───────────────→ Profile[] (fallbackData []) ─→ profiles page (async auth)
```

## Data-Access Layer
All hooks `"use client"`; `useSWR<Dto | null>(key, fetcher ?? null, { fallbackData: null })`.

| Hook | Signature | SWR key | DTO (reused) | Today |
|---|---|---|---|---|
| `useAnalyticsOverview` | `(range: RangeKey, fetcher?)` | `` `analytics-overview:${range}` `` | `OverviewSnapshot` | `data: null` → empty |
| `useGateway` | `(range: RangeKey, isCustom = false, fetcher?)` | `` `analytics-gateway:${range}:${isCustom}` `` | `GatewaySnapshot` | `data: null` → empty |
| `useBilling` | `(fetcher?)` | `billing-state` | `BillingState` | `data: null`; `setPlan`/`addTokens` optimistic `mutate(..., false)` kept |
| `useDashboardHome` | `()` | `dashboard-home` | `DashboardHomeSnapshot` | derives `kpis` via `deriveKpisFromSessions`, `volume` via `buildVolumeSeries(sessions, "7d")`, `recent` from sessions |
| `useVolume` | `(range: DashboardRange)` | `` `dashboard-volume:${range}` `` | `VolumePoint[]` | `buildVolumeSeries(sessions, range)` (sync) |
| `useRemoteBrowsers` | `(fetcher?)` | `remote-browsers` | `RemoteBrowserRow[]` (new) | `data: null` → skeleton + empty card |
| `useProfiles` | `()` | `execution-profiles` | `Profile[]` | unchanged `fallbackData: []`; `setProfileAuth` async |

`DashboardHomeSnapshot` = `{ kpis: DashboardKpis; volume: VolumePoint[]; recent: AgentSessionSnapshot[] }` — add to `lib/dashboard/types.ts`.

## File Changes
| File | Action |
|---|---|
| `lib/analytics/mock.ts` | Delete (only fully-removed mock) |
| `lib/dashboard/mock.ts` | Rename → `derive.ts` (bodies byte-identical; keep `browserSessions: 0` documented placeholder) |
| `lib/dashboard/types.ts` | Modify — add `DashboardHomeSnapshot` (only type change) |
| `lib/remote-browser/types.ts` | Create — `RemoteBrowserRow` (browser, cdpUrl, live, profileId, agent, region, startedAt, duration, cost) |
| `hooks/use-{analytics-overview,gateway,dashboard-home,volume,remote-browsers}.ts` | Create — hooks above |
| `hooks/use-billing.ts` | Modify — drop `INITIAL_BILLING_STATE`; `fallbackData: null`; `+data/isLoading/error`; mutate base `ZERO_BILLING_STATE` |
| `hooks/use-profiles.ts` | Modify — `setProfileAuth` async (await cache-mutate); no delay |
| `components/analytics/analytics-overview.tsx` | Modify — `import type { OverviewSnapshot }`; hook; optional `data/isLoading`; `isEmpty = !data \|\| data.kpis.totalUsed <= 0`; skeleton via `Skeleton` |
| `components/analytics/llm-gateway-panel.tsx` | Modify — drop `getGateway` import, `simulateEmpty`, `isCustom` state + Custom range UI; hook; `isEmpty = !data \|\| data.kpis.requests <= 0` |
| `components/dashboard/dashboard-view.tsx` | Modify — `useDashboardHome()`; pass `kpis`/`recent`/sessions; `isLoading` skeletons |
| `components/dashboard/kpi-row.tsx` | Modify — optional `isLoading` → `Skeleton` tiles |
| `components/dashboard/volume-chart.tsx` | Modify — `useVolume(range)` replaces `buildVolumeSeries` import; `+isLoading` |
| `components/dashboard/recent-activity-table.tsx` | Modify — `+isLoading` → skeleton rows |
| `components/remote-browser/remote-browser-table.tsx` | Create — client table: skeleton / `data.length===0` empty card / rows |
| `app/(chat)/remote-browser/page.tsx` | Modify — delete `DUMMY_BROWSERS`; render `<RemoteBrowserTable dict />` |
| `app/(chat)/settings/billing/page.tsx` | Modify — drop `USAGE_DATA`; `UsageChart` empty guard: `data.length===0` → empty card, no `Math.max(...,1)` NaN path; skeleton on loading |
| `app/(chat)/settings/profiles/page.tsx` | Modify — `handleSetupAuth` awaits `setProfileAuth` (no `setTimeout`) |
| `i18n/dictionary.ts` | Modify — `settings.billing.loadingUsage`/`emptyUsage` (en/es) |

Charts primitives, `agent-sessions`, `multimodal-input`, `panel-topbar`, `use-agent-sidebar.ts`, `backend/ai/tools/*`, `lib/billing/types.ts`, `lib/analytics/types.ts` — untouched.

## i18n Additions (`panel.pages.settings.billing`, en + es)
| Key | en | es |
|---|---|---|
| `loadingUsage` | "Loading usage..." | "Cargando uso..." |
| `emptyUsage` | "No usage in this period yet." | "Todavía no hay uso en este período." |

All other views reuse existing keys: `overviewUi.empty.*`, `llmGatewayUi.empty.*`, `home.volume.*`/`home.recentActivity.*`, `remoteBrowser.empty`, `settings.profiles.*`.

## Component Prop Contracts
| Component | New props | Loading | Empty |
|---|---|---|---|
| `AnalyticsOverview` | `data?: OverviewSnapshot \| null`, `isLoading?: boolean` | `Skeleton` KpiCards/charts | `OverviewEmpty` (existing) |
| `LlmGatewayPanel` | `data?: GatewaySnapshot \| null`, `isLoading?: boolean` | skeleton KPI row + 2×2 placeholders | `GatewayEmpty` (existing) |
| `DashboardView` | `data?: DashboardHomeSnapshot \| null`, `isLoading?: boolean` | skeleton KpiRow/Volume/Recent | existing branches |
| `KpiRow` | `isLoading?: boolean` | skeleton tiles | `0`-values |
| `VolumeChart` | `isLoading?: boolean` (keeps `sessions`) | skeleton | existing `isEmpty` |
| `RecentActivityTable` | `isLoading?: boolean` (keeps `sessions`) | skeleton rows | existing empty |
| `RemoteBrowserTable` | `dict` | skeleton rows | `dict.empty` |

## Testing / Verification
| Check | Command |
|---|---|
| Type check | `pnpm --filter frontend exec tsc --noEmit` |
| Build | `pnpm --filter frontend build` |
| e2e | `pnpm --filter frontend test` (no mock-number assertions — unchanged) |
| Grep-assert | zero hits in `frontend/` for `getOverview\|getGateway\|INITIAL_BILLING_STATE\|USAGE_DATA\|DUMMY_BROWSERS\|deterministicRandom` |
| Rename proof | `diff lib/dashboard/mock.ts lib/dashboard/derive.ts` → identical |

## Threat Matrix
N/A — no routing, shell command, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary introduced or modified.

## Migration / Rollout
None — no data migration or feature flags. Single atomic commit; rollback = `git revert` (proposal rollback plan).

## Open Questions
- [ ] Billing page when `data: null`: plan cards show no active plan — confirm acceptable (assumed yes).
- [ ] Confirm `settings.profiles.simulating` label is retained for the awaiting-auth button.