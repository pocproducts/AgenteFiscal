# Design: Auth + Tenant (port/adapter for mock-now / Clerk-later)

## Technical Approach

Keep NextAuth v5 as the SESSION layer, but move all DATA access behind an `AuthPort` boundary. `lib/auth/port.ts` defines the interface; an in-memory adapter delegates to `lib/db/queries.ts` (per-process store); a Clerk adapter STUB shares the signatures and throws. The client never touches adapters: `(chat)/layout.tsx` (server, behind `<Suspense>`) resolves `auth()` + tenant via the adapter into serializable props, seeds the client `<AuthProvider>`, and every consumer reads `useAuth()`. Mutations are server actions that persist through the adapter, update the JWT (`tenantId` only), then `router.refresh()` re-seeds — no `auth()`/`useSession()` drift.

## Architecture Decisions

| ID | Decision | Option | Tradeoff | Decision |
|----|----------|--------|----------|----------|
| D1 | Port shape | (a) 6 spec methods; (b) 6 + `verifyCredentials` | (b) hides bcrypt from NextAuth, making Clerk swap complete; (a) leaks hashing strategy | **(b)** — 6 spec methods + `verifyCredentials(email, password)`. Types `AuthUser`, `Tenant`, `AuthSeed`. Errors reuse `ChatbotError` (`bad_request:auth`, `not_found:auth`); the `user_exists`/`failed` UI contract stays as action status codes (spanish-panel D5 pattern) |
| D2 | Adapter selection | (a) env flag read per call; (b) cached factory | (a) re-reads env, testable; (b) one lookup | **(b)** — `getAuthAdapter()` factory in `lib/auth/adapters/index.ts`, module-level cache, env `AUTH_ADAPTER` (`in-memory` default \| `clerk`). Stub throws `Error("[clerk] not implemented")` |
| D3 | Tenant model | (a) `tenantId` on `User`; (b) separate `Tenant` + membership | (a) 1 tenant/user, breaks `listTenantsForUser`; (b) n:n, matches Clerk orgs | **(b)** — `Tenant { id, name, slug, ownerUserId, createdAt }` + `TenantMember { tenantId, userId }` in `lib/db/schema.ts` |
| D4 | Seed plumbing | (a) provider in root layout; (b) provider inside `SidebarShell` (behind Suspense) | (a) no session on landing, violates Next 16; (b) covers whole panel | **(b)** — `SidebarShell` resolves `Promise.all([auth(), cookies()])` + adapter calls → `AuthSeed` props → `<AuthProvider seed>` wrapping `<SidebarProvider>`. Covers AppSidebar, SidebarHistory, ChatHeader, ChatShell |
| D5 | Tenant UI | (a) only sidebar-user-nav; (b) nav dropdown + chat-header badge | (a) hidden while chatting; (b) two spots, one mutation source | **(b)** — `TenantManager` (tenant list + create dialog) inside sidebar-user-nav; passive current-tenant badge in `ChatHeader` |
| D6 | Server actions | (a) extend `(auth)/actions.ts`; (b) new `(chat)/actions.ts` | (b) keeps credential flows separate from panel ops | **(b)** — `createTenantAction`, `switchTenantAction`, `signOutAction`. Zod: `name.trim().min(1).max(50)`. Persist via adapter → `update({ tenantId })` (NextAuth `update` export) → `revalidatePath` + client `router.refresh()` |
| D7 | i18n | exactly the 7 spec keys under `panel.tenant.*` | none | Add sibling to `panel.sidebar` in BOTH `en` (line ~409) and `es` (line ~1102) dict trees in the same change |
| D8 | Component migration | migrate AppSidebar, SidebarUserNav, SidebarHistory to `useAuth()` | drops prop-drill of `User` | Drop `user` prop from all three; `AppSidebar`/`SidebarHistory` read `useAuth().user`, `SidebarUserNav` stops importing `next-auth/react` entirely |
| D9 | Session sync | (a) useSession().update(); (b) server `update()` + refresh | (b) single server truth; (a) client-only, drifts | **(b)** — all mutations go through server actions; provider re-seeds from fresh server props on `router.refresh()` |
| D10 | JWT size | full tenant object vs `tenantId` | full object bloats cookie | `tenantId: string \| null` only; name/slug fetched via adapter on seed |

## Data Flow

```
(chat)/layout ── SidebarShell (server, in <Suspense>)
   auth() + adapter.getTenantByUser(tenantId) + listTenantsForUser(userId)
   → AuthSeed {user, tenant, tenants} (serializable) → <AuthProvider seed>
   → AppSidebar / SidebarHistory / ChatHeader ── useAuth()
UI mutation ──createTenantAction(name)──→ adapter.createTenant → update({tenantId})
   → revalidatePath + router.refresh() → new seed → provider state syncs
Login/register ──(auth)/actions──→ adapter (getUserByEmail/createUser/verify)
   → NextAuth signIn("credentials") → JWT {id, type, tenantId}
```

## Interfaces / Contracts

```ts
// lib/auth/port.ts
export type AuthUser = { id: string; email: string | null; name?: string | null;
  type: "guest" | "regular" };
export type Tenant = { id: string; name: string; slug: string;
  ownerUserId: string; createdAt: Date };
export type AuthSeed =
  | { status: "authenticated"; user: AuthUser;
      tenant: Tenant | null; tenants: Tenant[] }
  | { status: "unauthenticated" };   // /chat reachable without a session
export interface AuthPort {
  getUserByEmail(email: string): Promise<AuthUser | null>;
  createUser(email: string, password: string): Promise<AuthUser>;
  createGuestUser(): Promise<AuthUser>;
  verifyCredentials(email: string, password: string): Promise<AuthUser | null>;
  getTenantById(tenantId: string): Promise<Tenant | null>;
  getTenantByUser(userId: string, tenantId: string): Promise<Tenant | null>;
  createTenant(userId: string, name: string, opts?: { gateToRegular?: boolean }): Promise<Tenant>;
  listTenantsForUser(userId: string): Promise<Tenant[]>;
}
```

`AuthProvider` (client) holds `seed` in state; a `useEffect` keyed on the **full seed identity** (`user.id` + `tenant.id`) re-syncs after refresh — NOT just `tenant.id` (a guest whose tenant.id stays `null` across a login change would otherwise never re-seed, leaving stale UI). `useAuth()` returns `{ user, tenant, tenants, status, isGuest, signIn, signOut, createTenant, switchTenant }`; `signIn`/`signOut` call server actions then `router.refresh()`.

### JWT/session `update()` contract (design D6/D9)

NextAuth v5 delivers a server `update()` as `trigger: "update"` with `session: data` to the `jwt` callback. The callback MUST merge it:

```ts
jwt({ token, trigger, session }) {
  if (user) { token.id = user.id; token.type = user.type; }
  if (trigger === "update") { token.tenantId = session.tenantId; }
  return token;
}
```

Without the `trigger === "update"` branch the token never updates after `createTenant`/`switchTenant`, reintroducing the `auth()`/`useAuth()` drift D9 is meant to remove. `app/(auth)/auth.ts` also needs `update` added to the `NextAuth()` destructure (currently exports only `{ GET, POST, auth, signIn, signOut }`).

### Open Questions — resolved

- **Guest tenant creation**: gate `createTenant` to `regular` users. Anonymous guests creating tenants would pollute the shared store and confuse the login flow. The server action rejects `guest` (auth error surfaced to UI); UI hides the create affordance for guests.
- **Auto-select on create**: auto-select the newly created tenant as current + `tenantCreated` toast. Depends on the `trigger: "update"` merge above; if the JWT update fails, `router.refresh()` re-seeds from the adapter so state self-corrects.

## Affected Areas

| File | Action | Description |
|------|--------|-------------|
| `lib/auth/port.ts` | Create | Interface + types (above) |
| `lib/auth/adapters/in-memory.ts`, `clerk.ts`, `index.ts` | Create | Delegating adapter, throwing stub, factory |
| `lib/auth/provider.tsx` | Create | Client `AuthProvider` + `useAuth` |
| `lib/db/schema.ts` | Modify | `Tenant`, `TenantMember` interfaces |
| `lib/db/queries.ts` | Modify | `tenants`/`tenantMembers` arrays + 4 tenant fns |
| `app/(auth)/auth.ts` | Modify | JWT/session `tenantId`, export `update`, authorize via adapter |
| `app/(auth)/actions.ts` | Modify | register/login route through adapter |
| `app/(chat)/actions.ts` | Modify | add `createTenantAction`, `switchTenantAction`, `signOutAction` (file already exists) |
| `app/(chat)/layout.tsx` | Modify | Seed resolve + `<AuthProvider seed>` in `SidebarShell` |
| `components/chat/tenant-manager.tsx` | Create | Tenant list + create dialog (reusable) |
| `components/chat/{app-sidebar,sidebar-history,sidebar-user-nav,chat-header}.tsx` | Modify | `useAuth()`, tenant badge |
| `lib/i18n/dictionary.ts` | Modify | `panel.tenant.*` en/es |

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| E2E | `auth.test.ts` | Register → create tenant → name visible in header; wrong-password login fails |
| E2E | tenant flow | Create tenant, switch, restart wipe → `noTenants` |
| E2E | i18n | Assert `es` copy ("Crear tenant") and `en` copy |

## Migration / Rollout

No DB migration (in-memory only). Chained PRs: (1) port+adapters+schema, (2) seed+provider+layout, (3) actions+i18n, (4) UI components. Each reverts independently.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Next 16 blocking `cookies()`/`auth()` | Seed stays inside existing `<Suspense>` (proven pattern) |
| `auth()`/useAuth() drift | Single mutation path: action → `update()` → `revalidatePath` → refresh |
| Hydration mismatch | Seed is plain strings; provider never defaults client-side |
| JWT size | `tenantId` only (D10) |
| `update()` server export missing | Add to NextAuth destructure in `auth.ts` (v5 API) |

## Implementation Steps

1. `lib/db/schema.ts` — `Tenant`, `TenantMember`; `lib/db/queries.ts` — tenant arrays + `createTenant`, `getTenantById`, `getTenantByUser`, `listTenantsForUser`.
2. `lib/auth/port.ts` — interface + types.
3. `lib/auth/adapters/{in-memory,clerk,index}.ts` — adapter (delegates to queries.ts, one `Tenant` shape incl. `ownerUserId`/`createdAt`), stub, factory.
4. `app/(auth)/auth.ts` — `tenantId` in JWT/session module types + `jwt`/`session` callbacks incl. `trigger === "update"` branch; export `update`; authorize delegates to adapter.
5. `app/(auth)/actions.ts` — swap `lib/db/queries` imports for adapter.
6. `lib/auth/provider.tsx` — `AuthProvider` + `useAuth`, sync keyed on `user.id + tenant.id`, `unauthenticated` branch.
7. `app/(chat)/layout.tsx` — seed resolve + provider wrap behind existing `<Suspense>`.
8. `app/(chat)/actions.ts` — 3 actions (zod, adapter with `createTenant` gated to `regular`, `update()`, revalidate).
9. `lib/i18n/dictionary.ts` — `panel.tenant.*` (en+es together).
10. `components/chat/tenant-manager.tsx` + sidebar/header migrations (D8/D5).

## Testing notes (edge cases)

- Empty tenant name → zod validation rejects before adapter call (E2E).
- `noTenants` placeholder for authenticated user with no tenant (E2E, distinct from restart-wipe).
- In-memory store persists per process and `playwright.config.ts` uses `reuseExistingServer: !CI` → use unique email per test so an earlier test's registered user doesn't collide.
- `column` guest → ui hides create affordance; action rejects `guest`.
