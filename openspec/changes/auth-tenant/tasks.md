# Tasks: Auth + Tenant (port/adapter for mock-now / Clerk-later)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,600 (session budget: 2,000) |
| 400-line budget risk | High per-commit; Overridden (single PR + size exception) |
| Chained PRs recommended | No (4 slices = backstop only, delivered as ONE PR) |
| Suggested split | Single PR with `size:exception`; 4 work-unit commit groups |
| Delivery strategy | single-pr-exception |
| Chain strategy | size (exception approved) |

```text
Decision needed before apply: No
Chained PRs recommended: No (single PR, size exception approved)
400-line budget risk: Overridden (session budget 2,000, estimated ~1,600)
```

`single-pr-exception`: ALL change delivered in ONE PR (~1,600 lines, within the 2,000-line session budget). The work units below are apply-progress commit groups, not separate PRs.

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Port + adapters + schema/queries | PR #1 (integrated) | Base to main in the single PR; closest to independent — reverts alone |
| 2 | Seed/provider + chat layout | PR #1 | Depends on unit 1; sync key `user.id + tenant.id`, unauthenticated branch |
| 3 | Auth (JWT update trigger) + server actions + i18n | PR #1 | Depends on units 1-2; `trigger:"update"` contract, `update()` export |
| 4 | UI (tenant-manager + component migration) + E2E | PR #1 | Depends on units 2-3; drops `user` prop-drill |

## Phase 1 — DB/schema + queries

- [ ] 1.1 `lib/db/schema.ts` — add `Tenant { id, name, slug, ownerUserId, createdAt }` and `TenantMember { tenantId, userId }` interfaces (D3).
- [ ] 1.2 `lib/db/queries.ts` — add `tenants[]` and `tenantMembers[]` in-memory arrays next to existing store.
- [ ] 1.3 `lib/db/queries.ts` — add `createTenant(userId, name)` (generates id/slug, inserts owner member) returning `Tenant` (incl. `ownerUserId`/`createdAt`).
- [ ] 1.4 `lib/db/queries.ts` — add `getTenantById(id)`, `getTenantByUser(userId, tenantId)`, `listTenantsForUser(userId)` (filter via `tenantMembers`).
- [ ] 1.5 Risk (Next 16): keep all queries synchronous against the in-memory arrays; no async fetch layer needed.

## Phase 2 — Port (`lib/auth/port.ts`)

- [ ] 2.1 Create `lib/auth/port.ts` — export types `AuthUser`, `Tenant`, `AuthSeed` per design Interfaces/Contracts (unauthenticated branch included).
- [ ] 2.2 Add `AuthPort` interface — 8 methods: `getUserByEmail`, `createUser`, `createGuestUser`, `verifyCredentials`, `getTenantById`, `getTenantByUser`, `createTenant` (`opts?: { gateToRegular? }`), `listTenantsForUser`.
- [ ] 2.3 Reuse `ChatbotError` carriers (`bad_request:auth`, `not_found:auth`); keep `user_exists`/`failed` as action status codes (spanish-panel D5 pattern).

## Phase 3 — Adapters (`lib/auth/adapters/`)

- [ ] 3.1 Create `in-memory.ts` — implements `AuthPort` delegating to `lib/db/queries.ts`; `Tenant` shape matches port (1:1).
- [ ] 3.2 Create `clerk.ts` — stub with same signatures, each throws `Error("[clerk] not implemented")`.
- [ ] 3.3 Create `index.ts` — `getAuthAdapter()` factory, module-level cache, env `AUTH_ADAPTER` (`in-memory` default \| `clerk`) (D2).
- [ ] 3.4 Risk (drift): one source of truth — adapters must NOT re-define `Tenant`; import the port type.

## Phase 4 — `app/(auth)/auth.ts` (JWT/session/adapter)

- [ ] 4.1 Add `tenantId: string | null` to JWT + session module types; carry only `tenantId`, never full tenant (D10).
- [ ] 4.2 Extend `jwt` callback: set `token.id`/`token.type` from `user`; merge `token.tenantId = session.tenantId` only when `trigger === "update"`.
- [ ] 4.3 Add `update` to the `NextAuth()` destructure (export it) — currently exports only `{ GET, POST, auth, signIn, signOut }`.
- [ ] 4.4 Extend `session` callback to surface `user.type` + `tenantId`; route `authorize` through the adapter (`verifyCredentials`).
- [ ] 4.5 Risk: missing `trigger:"update"` branch reintroduces `auth()`/`useAuth()` drift (D9) — verify branch present + tested.

## Phase 5 — Actions: auth (`app/(auth)/actions.ts`)

- [ ] 5.1 Register action — adapter `createUser` (map existing-email → `user_exists`); zod password ≥6 before adapter call.
- [ ] 5.2 Login action — adapter `verifyCredentials`; wrong password → `failed` status, no session.

## Phase 6 — AuthProvider client + useAuth (`lib/auth/provider.tsx`)

- [ ] 6.1 Create `AuthProvider` — holds `seed` in state; exposes `{ user, tenant, tenants, status, isGuest, signIn, signOut, createTenant, switchTenant }`.
- [ ] 6.2 `useEffect` re-sync keyed on FULL identity `user.id + tenant.id` (NOT just `tenant.id`) so a guest→login change re-seeds (design sync note); handle unauthenticated seed branch.
- [ ] 6.3 Provider never defaults client-side (plain string seed → no hydration mismatch risk).
- [ ] 6.4 `signIn`/`signOut` call server actions then `router.refresh()` (single mutation path, D9).

## Phase 7 — App layout seed (`app/(chat)/layout.tsx` + `SidebarShell`)

- [ ] 7.1 Resolve seed in `(chat)` layout behind existing `<Suspense>`: `Promise.all([auth(), cookies()])` + `getTenantByUser` + `listTenantsForUser` → serializable `AuthSeed`.
- [ ] 7.2 Wrap `<AuthProvider seed>` inside `SidebarShell` around `<SidebarProvider>` (covers AppSidebar, SidebarHistory, ChatHeader, ChatShell) (D4).

## Phase 8 — Server actions (`app/(chat)/actions.ts`)

- [ ] 8.1 `createTenantAction(name)` — zod `name.trim().min(1).max(50)`; reject guest via `createTenant` gate (auth error); adapter create → `update({ tenantId })` → `revalidatePath` + client refresh; auto-select new tenant + `tenantCreated` toast.
- [ ] 8.2 `switchTenantAction(tenantId)` — adapter lookup; `update({ tenantId })` + revalidate/refresh.
- [ ] 8.3 `signOutAction()` — NextAuth `signOut` + revalidate/refresh.
- [ ] 8.4 Risk: auto-select depends on `trigger:"update"` merge; if JWT update fails, `router.refresh()` re-seeds from adapter (self-correct).

## Phase 9 — i18n (`lib/i18n/dictionary.ts`)

- [ ] 9.1 Add `panel.tenant.*` sibling to `panel.sidebar` in `en` (~line 409): `createTenant`, `currentTenant`, `tenantName`, `switchTenant`, `tenantCreated`, `noTenants`, `placeholder`.
- [ ] 9.2 Add the SAME 7 keys in `es` tree (~line 1102) in the same change — no dict drift (REQ 5, D7).

## Phase 10 — UI components

- [ ] 10.1 Create `components/chat/tenant-manager.tsx` — tenant list + create dialog + switch (reusable).
- [ ] 10.2 `components/chat/app-sidebar.tsx` — drop `user` prop; read `useAuth().user` (D8).
- [ ] 10.3 `components/chat/sidebar-history.tsx` — drop `user` prop; `useAuth().user` (D8).
- [ ] 10.4 `components/chat/sidebar-user-nav.tsx` — stop importing `next-auth/react`; mount `TenantManager`; hide create affordance for guest (D5/D7).
- [ ] 10.5 `components/chat/chat-header.tsx` — passive current-tenant badge via `useAuth().tenant` (D5); show tenant name or `noTenants` placeholder.
- [ ] 10.6 Risk: hydration mismatch — all data flows from serializable seed only; no client default.

## Phase 11 — E2E tests

- [ ] 11.1 Update `tests/e2e/auth.test.ts` — register→create tenant→name visible in header; wrong password fails; empty name rejected by zod; use UNIQUE email per test (playwright `reuseExistingServer: !CI` collisions).
- [ ] 11.2 New tenant E2E — create, switch, restart wipe → `noTenants` state.
- [ ] 11.3 New guest-gate E2E — guest sees hidden create affordance; direct action rejects `guest`.
- [ ] 11.4 i18n E2E — assert `es` ("Crear tenant") and `en` copy separately.
- [ ] 11.5 Update existing tests that relied on `user` prop-drill to use the new `useAuth()` data-selectors.

## Phase 12 — Verification (user-run, no bash here)

- [ ] 12.1 User runs `pnpm test` — all E2E green (auth-tenant, existing chat/auth).
- [ ] 12.2 User runs `pnpm build` — TS strict + tsconfig green (next build).
- [ ] 12.3 User runs `pnpm dev` — manual: register → create tenant → badge; switch; restart → noTenants; `es`/`en` copy correct.
- [ ] 12.4 Lint/format: user runs `pnpm check` / `pnpm fix`.

## Risks Summary

| Phase | Risk | Mitigation |
|-------|------|------------|
| 7/8 | Next 16 blocking `cookies()`/`auth()` | Seed inside existing `<Suspense>` (proven pattern) |
| 4/8 | `auth()`/`useAuth()` drift | Single mutation path: action → `update()` → revalidate → refresh; `trigger:"update"` branch |
| 4 | `update()` export missing | Add to NextAuth destructure (v5 API) |
| 10 | Hydration mismatch | Seed plain strings; provider never defaults client-side |
| 3 | Adapter/port type drift | Shared types in `port.ts`; adapters import, never re-declare |