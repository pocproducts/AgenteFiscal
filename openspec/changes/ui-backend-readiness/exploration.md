# Exploration: ui-backend-readiness

Date: 2026-08-06. Read-only map of every invented/fixture mock source in the panel UI,
and the target architecture (typed contracts + loading/data/error hooks + empty/loading
states) for wiring the real backend later.

Scope decision (already agreed, NOT revisited): the fiscal tools/agent flow
(`backend/ai/tools/*`, `agent-composer` → chat stream → `useAgentSidebar` monitor session
persistence, `sidebar-history`) is the production template and is KEPT untouched.

---

## 1. Mock inventory table

| Area | File | Invented symbol(s) | Consumers | Empty-state today? |
|------|------|--------------------|-----------|--------------------|
| **Analytics** | `frontend/lib/analytics/mock.ts` | `deterministicRandom`, `getOverview(range)`, `getGateway(range, isCustom)`, `RANGE_LABELS`, `REFERENCE_END` (hard-pinned `2026-07-12`), `MODEL_SPECS`, `BYOK_PROVIDERS`, PRNG seeds | `analytics-overview.tsx` (line 29, `getOverview`), `llm-gateway-panel.tsx` (line 34, `getGateway`) | Yes (see §4) |
| | `frontend/lib/analytics/types.ts` | NONE — all types (`OverviewSnapshot`, `GatewaySnapshot`, `Kpis`, point/row interfaces) are clean contracts; **reuse these, don't delete** | chart components, panels | — |
| **Billing** | `frontend/hooks/use-billing.ts` | `INITIAL_BILLING_STATE` = `{ tokenBalance: 12_000, usdBalance: 45, currentPlan: "Free" }` | `token-balance-widget.tsx`, `plan-badge-widget.tsx`, `settings/billing/page.tsx` | No — always renders the fallback numbers |
| | `frontend/app/(chat)/settings/billing/page.tsx` | `USAGE_DATA` (hardcoded 30d `UsageWeek[]`, lines 33–50), `RECHARGE_AMOUNTS` (static, fine but UI-only), inline `UsageChart` SVG | the page itself | No — chart renders raw zeros if `data=[]` but data is always non-empty |
| **Dashboard** | `frontend/lib/dashboard/mock.ts` | **NOT random.** `deriveKpisFromSessions()` and `buildVolumeSeries()` are derived from real `useAgentSidebar` sessions. Only invented value: `browserSessions: 0` (hardcoded placeholder, no real browser-session hook yet). File name is misleading | `dashboard-view.tsx` (both), `volume-chart.tsx` (`buildVolumeSeries`) | Yes — `volume-chart` and `recent-activity-table` already render empty; `kpi-row` always shows `0`. |
| | `frontend/app/(chat)/remote-browser/page.tsx` | `DUMMY_BROWSERS` (2 hardcoded browser rows; server component) | the page table | Empty branch exists (line 155) but is **dead code** (`DUMMY_BROWSERS.length` always 2) |
| **Profiles** | `frontend/hooks/use-profiles.ts` | Whole hook is client–local SWR (`"execution-profiles"`, `fallbackData: []`, null fetcher). ID gen `prof_${random}`; CRUD + `setProfileAuth` all in-memory only. Not a "fixture array", but no backend — **empty state already correct** | `settings/profiles/page.tsx`, `agent-sessions/page.tsx` (profile name lookup), `multimodal-input.tsx` (selector) | Yes — `profiles.length === 0` empty card + `empty`/`createFirst` keys |
| | `settings/profiles/page.tsx` | Fake auth flow: `handleSetupAuth` uses `setTimeout(…,1500)` + `dict.simulating`; `AVAILABLE_DOMAINS` hardcoded list | the page | Yes (empty card) |
| **Other** | `frontend/components/chat/agent-sidebar.tsx` | Line 147 comment `{/* Browser viewport — mock content */}` | — | n/a (visual placeholder only) |
| | `frontend/hooks/use-billing.ts` | `addTokens` / `setPlan` mutate the in-memory SWR cache (`mutate(…, false)`), not persisted | billing page + widgets | — |

Consumers of fake data (import map):

- `analytics-overview.tsx` → `getOverview` (line 29 import, 98 call)
- `llm-gateway-panel.tsx` → `getGateway` (line 34 import, 223 call); also local `[simulateEmpty]` + `[isCustom]` mock toggles ("Simular Vacío" button, "SISTEMA LLM: ONLINE" badge)
- `dashboard-view.tsx` → `deriveKpisFromSessions`; `volume-chart.tsx` → `buildVolumeSeries`
- `use-billing.ts` consumers: `panel-topbar.tsx` → `TokenBalanceWidget` + `PlanBadgeWidget` (lines 48–49); `settings/billing/page.tsx` (lines 16, 239)

---

## 2. What is already real (keep)

- **Agent-session model** (`backend/ai/tools/agent-execution.ts` — KEEP): `AgentSession`, `AgentSessionSnapshot`, `AgentTask`, `TaskStatus`, `AgentSessionStatus`, `buildSubtasksForTool`, `generateAgentId`. Real fields incl. `startedAt`, `completedAt`, `totalCostCents`.
- **Session persistence / hydration**: `frontend/hooks/use-agent-sidebar.ts` persists via SWR-localStorage; `hydrate()` restores completed sessions from chat activity; `frontend/components/chat/sidebar-history.tsx` (history list). Dashboard KPIs already derive from these sessions.
- **`useAgentSidebar`** feeds `dashboard-view` `allSessions` → real KPI/volume/recent-activity.
- **Empty…** (partially): `volume-chart` (`isEmpty = values.every(v => v===0)`), `recent-activity-table` (`recent.length === 0`), `settings/profiles` empty card — all render real client-state empties already.

---

## 3. Proposed typed contracts

General rule (mirror `useBilling` SWR pattern — `useSWR<Dto>(key, fetcher|later, {fallbackData})` → returns `{ …data, isLoading ?, error }`):

| Domain | Dto/Dto type (new file) | Hook | Reuse vs rename |
|--------|------------------------|------|-----------------|
| **Analytics overview** | `OverviewSnapshot` — KEEP EXACT interface in `lib/analytics/types.ts` (drop nothing from `OverviewSnapshot`) | `useAnalyticsOverview(range)` → `{ data?: OverviewSnapshot \| null, isLoading, error, mutate }`, cache key per range, e.g. `"analytics-overview:{range}"` | Reuse `OverviewSnapshot`, `DayConsumption`, `SessionPoint`, `TaskPoint`, `BrowserPoint`, `OverviewKpis`, `SessionKpis`, `TaskKpis` as-is. **Do not** import value symbols from `mock.ts` |
| **LLM gateway** | `GatewaySnapshot` — KEEP EXISTING `GatewaySnapshot`, `GatewayKpis`, `GatewayPoint`, `ModelBreakdownRow`, `ByokProvider` | `useGateway(range, isCustom)` → `{ data: GatewaySnapshot \| null, isLoading, error, mutate }`. Key e.g. `"analytics-gateway:{range}:{isCustom}"` | Reuse all above. `ByokProvider` is a **description only** (i18n label/description). Rename nothing; add an `activeProviders`/`credentials` field as separate endpoint when real |
| **Billing** | `BillingState` — KEEP `lib/billing/types.ts` `BillingState { tokenBalance, usdBalance, currentPlan }` | Replace `useBilling` internals: keep signature, add `isLoading` + `error`; keep `setPlan`/`addTokens` as cache-mutate + optimistic, then `.revalidate()`. Move `INITIAL_BILLING_STATE` to a real `fetcher` | Reuse `BillingState`, `BillingPlanId` unchanged |
| **Dashboard home** | `lib/dashboard/types.ts` — add `DashboardHomeSnapshot` or reuse `{ kpis: DashboardKpis, volume: VolumePoint[], recent: AgentSessionSnapshot[] }` wrapper. Existing `DashboardKpis`, `VolumePoint` correct | `useDashboardHome()` → `{ data, isLoading, error }`; `useVolume(range)` → reuses `buildVolumeSeries`. **Move `buildVolumeSeries` + `deriveKpisFromSessions` OUT of `mock.ts`** into a real module (e.g. `lib/dashboard/derive.ts` or `lib/dashboard/api.ts`) — keep them as pure derivation from sessions | Reuse `DashboardKpis`, `DashboardRange`, `VolumePoint`. **Rename/relocate** the file `mock.ts` → `derive.ts`/`api.ts` (it was never random mock). `browserSessions` remains a `0`-placeholder field |
| **Profiles** | `lib/profiles/types.ts` (new, or keep `Profile` in `hooks/use-profiles.ts`) | `useProfiles()` → mirror `useBilling`: `{ profiles, isLoading?, error, add/update/delete/auth }`; auth becomes async (remove `setTimeout` fake) | Reuse `Profile` interface. `Profile.id` type is fine `string` |
| **Remote browser** | `lib/remote-browser/types.ts` (new DTO) — `RemoteBrowserRow {}` matching the table | `useRemoteBrowsers()` → `{ data, isLoading, error }` | New; delete `DUMMY_BROWSERS` |

View components that need a `data` prop added (they currently take `dict` + already-typed arrays):

- `analytics-overview.tsx` — receives `OverviewSnapshot` (its own `AnalyticsOverview` uses `getOverview`); add `data: OverviewSnapshot \| null` + `isLoading?` prop. Keep `RangeSwitcher` local.
- `llm-gateway-panel.tsx` — add `data: GatewaySnapshot \| null`. `simulateEmpty` toggle → replace with real `isLoading`/`error` board.
- `dashboard-view.tsx` — add `data` prop feeding `KpiRow`/`VolumeChart`/`RecentActivityTable` (or `useDashboardHome` inside).
- `kpi-row.tsx` — already takes `kpis: DashboardKpis` — correct, keep.
- `volume-chart.tsx` — add `sessions` already real; add `loading` prop for skeleton.
- `recent-activity-table.tsx` — takes `sessions` — correct, add `loading` prop.
- `token-balance-widget.tsx` / `plan-badge-widget.tsx` — silent, `useBilling` provides `data/loading`/`error`; widget can render `—`/skeleton while loading; already fine with `fallbackData`.
- `settings/billing/page.tsx` — replace `USAGE_DATA` prop on `UsageChart` with `data` from a `useBillingUsage()`. `UsageChart` already takes `data: UsageWeek[]` — keep the `UsageWeek` shape, reuse for typed DTO.
- Chart primitives (`components/analytics/charts/*`) — take **demilitarized** array props (`labels`, `series`, `data: DayConsumption[]`, `AreaLinePoint[]`) and `title/emptyTitle`/`emptyRecommendation` — no DTO coupling, good, keep.

Reuses vs renames (summary): rename `frontend/lib/dashboard/mock.ts` → `frontend/lib/dashboard/derive.ts` (renamed file, same functions `deriveKpisFromSessions`/`buildVolumeSeries`) — it was never mock. And `frontend/lib/analytics/mock.ts` is the only file fully deleted.

---

## 4. Empty / loading state plan

i18n keys in `frontend/i18n/dictionary.ts` are bilingual (en/…/es), nested `panel.pages…`.

| View | Loading (skeleton) | Empty state | i18n keys (exist vs need) |
|------|--------------------|-------------|----------------------------|
| **Analytics overview** | Skeleton KpiCard / chart cards using `<Skeleton>` (exists `components/ui/skeleton.tsx`) | `OverviewEmpty` (already implemented, `analytics-overview.tsx` lines 74–90) keyed off `snapshot.kpis.totalUsed <= 0` | `overviewUi.empty.title`+`.recommendation` EXIST — need `loading` label? Not required if skeleton used. |
| **LLM gateway** | Skeleton KPI row + 2×2 chart placeholders | `GatewayEmpty` (already exists, lines 73–133) driven by `isEmpty`; **remove the `Simular Vacío` + `custom` mock toggles** | `llmGatewayUi.empty.title`+`.recommendation` (exist). Need key for loading state |
| **Billing page** | Skeleton `UsageChart` + balance tile | `UsageChart` handle `data.length === 0` (currently no empty guard → `Math.max(…,1)` + line path of `/0` = NaN) | uses `settings.billing.*` — needs new `empty` key (e.g. `settings.billing.emptyUsage`) and `loading` key |
| **Dashboard home** | `Skeleton` for KpiRow, VolumeChart, RecentActivity | VolumeChart + RecentActivity empty branches already exist; KpiRow shows `0` | `home.volume.emptyTitle/Description`, `home.recentActivity.empty` existing. Add `loading` keys for the three |
| **Profiles** | `useProfiles` `fallbackData: []` — empty card already the loading proxy; add explicit `SkeletonSavings`/cards for `isLoading` | Already implemented (`profiles.length === 0` → Users icon card + `createFirst`) | `settings.profiles.empty`, `.createFirst` exist |
| **Remote browser** | Skeleton rows | Dead `DUMMY_BROWSERS.length === 0` branch — wire to `data.length` | `remoteBrowser.empty` exists |

Add any loading label key under existing dict roots. Nothing else hard to add.

---

## 5. Risks

1. **Chart empty rendering**: `bar-columns`/`area-line`/`stacked-bar` all `canRender = … data.length>0 && max>0` → render `emptyTitle` block. Safe on empty arrays. BUT `stacked-bar` `niceTicks` on `maxTotal 0` → `return [0]` → `scaleMax = 0`; canRender `== 0` → empty block, fine. `Settings billing UsageChart` **has no empty guard** — drops to `maxAmount`=1 and `points[0]` = undefined on/empty array → crash unless guarded.
2. **Charts assume non-empty series** in `analytics-overview` (the `dailySuccessRate` map, `sessions.map`, etc. — must guard with the existing `isEmpty` before building chart series; currently the `OverviewEmpty` block short-circuits, so safe as long as that branch is honored).
3. **Shared type import from `mock.ts`**: `lib/dashboard/mock.ts` is imported only by `dashboard-view` + `volume-chart` (both will be updated). `lib/analytics/mock.ts` imported by the two panels. No external consumers — drop safe after updating those 4 callers. Beware `change.yaml` `proposal` only lists removal — keep `analytics/types.ts` imports intact across the value modules (types-only re-export is fine).
4. **e2e/Playwright**: tests (`tests/e2e/api.test.ts`, `chat.test.ts`, `model-selector.test.ts`, `auth.test.ts`) do NOT assert mock numbers (grep for `12,000`/`billing`/`analytics` → none). Low risk.
5. **`useBilling` mutation semantics**: current `addTokens`/`setPlan` mutate the local SWR cache. When real fetcher lands, keep `mutate(data => …, false)` (optimistic) then revalidate; do NOT delete the API so topbar still works offline.
6. **`Profile` auth setProfileAuth fake** — removing the `setTimeout` while keeping `setProfileAuth` requires the real endpoint; keep the hook signature stable so `settings/profiles` page + `multimodal-input` + `agent-sessions` (profile-name lookup) keep compiling. Also keep `Profile.id` shape (`string`) — `agent-sessions/page.tsx` expects `profiles.find(p => p.id === profileId)`.
7. **`browserSessions` naming**: it's a constant `0` placeholder; no synthesis to 0 from sessions — leave as a documented placeholder until real browser session tracking exists (out of scope for this change).
8. **`GatewayPanel isCustom` `simulateEmpty`** currently passes both to `getGateway`; when replaced by real hook, keep `RangeKey` union (`24h|7d|30d|90d`) and add `custom` only when backend/real supports it — avoid breaking the `RangeSwitcher` `onChange(key: string)` signature.
9. **No GET API for analytics** yet; `SWR` with a future `fetcher` is a thin contract — hooks must accept a `fetcher` param/default and not hard-core into `mock`. Keep `loading/error` optional so the today-`fallbackData` path still renders.

---

## Ready for Proposal

**Yes.** The scope is well-defined, the two panel/analytics mock files are isolate, all consumers identified, i18n empty keys mostly exist, and no parent concerns block the design phase. Design can proceed directly from this map.