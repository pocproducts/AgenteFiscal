# Exploration: Clerk Migration for Register/Login/Tenant (hexagonal, first real migration)

## Current State

Auth today is **NextAuth v5 (`5.0.0-beta.25`)** + a **file-persisted in-memory mock DB**. No middleware file exists. Spanish-first (es default) i18n drives all auth + panel copy.

- `app/(auth)/auth.ts` — `NextAuth({...})` with two **Credentials** providers: email/password (`authorize` → `lib/db/queries.getUser()`, bcrypt verify) and `id: "guest"` (`authorize` → `createGuestUser()`). Bulks JWT/session to carry `{ id, type }`. No `update` exported. Uses `DUMMY_PASSWORD` (timing-safe) from `lib/constants.ts`.
- `app/(auth)/auth.config.ts` — basePath `/api/auth`, `trustHost`, pages signIn→`/login`, newUser→`/chat`.
- `app/(auth)/actions.ts` (server actions) — `register` (zod email + pass ≥6; `getUser` → `user_exists`; `createUser`; `signIn("credentials")`) and `login` (`signIn("credentials")`). Return status codes consumed by pages.
- `app/(auth)/login/page.tsx` + `register/page.tsx` — client pages using `useActionState(login/register)`, `useSession().update()`, `router.refresh()`, `AuthForm` + `SubmitButton`, `toast`, `t.auth.*` copy. `AuthForm` is a **custom** email/password form.
- `app/(auth)/api/auth/[...nextauth]/route.ts` — NextAuth route handler. `app/(auth)/api/auth/guest/route.ts` — guest sign-in route (redirects, or `signIn("guest")`).
- `app/(auth)/layout.tsx` — auth route group layout.
- `app/layout.tsx` — global `SessionProvider` (next-auth/react, basePath `/api/auth`) wrapping `ThemeProvider > LanguageProvider(es) > TooltipProvider`. (**ClerkProvider would replace SessionProvider here.**)
- `app/(chat)/layout.tsx` — `SidebarShell` (server): `Promise.all([auth(), cookies()])` → `<AppSidebar user={session.user}` behind Suspense. **This is where the auth-tenant blueprint injects `AuthProvider`.**
- Session consumers: `sidebar-user-nav.tsx` (`useSession()` from next-auth/react, `guestRegex`, theme + sign-out/login; drops to `/login` for guests), `app-sidebar.tsx` (`user` prop drill), `sidebar-history.tsx` (`user` prop drill to gate the history SWR call), `chat-header.tsx` (currently no session — target for tenant badge). `auth-form.tsx` (custom form).
- Data: `lib/db/queries.ts` (`getUser`, `createUser`, `createGuestUser`, chats/docs/... keyed by `userId`) + `lib/db/schema.ts` (`User` type; blueprint adds `Tenant`/`TenantMember`). `lib/constants.ts` — `DUMMY_PASSWORD`, `guestRegex`. `app/(chat)/api/history/route.ts` — protected by `await auth()`, chats keyed by `session.user.id`.
- Testing: Playwright E2E only (`tests/e2e/auth.test.ts` asserts **Spanish** copy on `/login` + `/register`; `pnpm test`). No unit/integration.

## Blueprint — `openspec/changes/auth-tenant/` (planned, NOT applied)

Readable proposal/spec/design/tasks. It ships a hexagon: `lib/auth/port.ts` (`AuthPort` with `getUserByEmail, createUser, createGuestUser, verifyCredentials, getTenantById, getTenantByUser, createTenant({gateToRegular?}), listTenantsForUser`; types `AuthUser`, `Tenant{id,name,slug,ownerUserId,createdAt}`, `AuthSeed` with authenticated|unauthenticated) + `adapters/in-memory.ts` (delegates to `queries.ts`), `clerk.ts` (throw stub), factory `getAuthAdapter()` (`AUTH_ADAPTER` env; in-memory default | clerk). Client `AuthProvider`/`useAuth()` seeded server-side in `SidebarShell` behind Suspense; mutations = server actions → `update({tenantId})` → refresh (kills auth()/useAuth drift). Session/JWT carries `tenantId` only. Tenant n:n via `TenantMember`. Guests gated from tenant creation. Risks: Next 16 blocking cookies/auth, auth()/useAuth() drift, hydration, adapter/port type drift.

**Key gap for Clerk:** the blueprint's session layer is **NextAuth** (JWT merge via `trigger:"update"`, `update()` export, Credentials authorize). Clerk replaces that session layer wholesale — so those specific NextAuth details are throwaway for the Clerk target.

## Clerk Current Reality (2026)

- **`@clerk/nextjs` v7.6.3** (July 2026). Peer deps: `next ^15.2.8||…||^16.0.10||^16.1.0-0`, `react ~19.0.3 || ~19.1.4 || ~19.2.3 || ~19.3.0-0`. **Project pins `react 19.0.1` (does NOT satisfy `~19.0.3`) and `next 16.2.0`.**
- **Next.js 16 renamed the middleware boundary file to `proxy.ts`** (project currently has NO middleware). Clerk supports App+Pages.
- **Security:** Next 16.2.0 is affected by `GHSA-26hh-7cqf-hhc6` (App Router Middleware/Proxy bypass, CVSS 7.5); patched in `next 16.2.6+`. Bump required when adding `clerkMiddleware`/`proxy.ts`.
- **`createRouteMatcher()` is deprecated** in `@clerk/nextjs` 7.5.14+ → prefer **resource-based checks** (`await auth.protect()` inside page/layout/route) for protection.
- `clerkMiddleware()` default = **all routes public**; opt-in protection. Matcher config from docs (skip static `_next`, run on API + `__clerk`).
- `ClerkProvider` (App Router) **auto-reads `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`**; wraps a client provider tree (replaces `SessionProvider`).
- **Server `auth()`** (`@clerk/nextjs/server`) — cheap (JWT cookie read, no network): returns `{ userId, orgId, orgRole, orgSlug, orgPermissions, sessionClaims, getToken }`. **`orgId`/`orgRole`/`orgSlug` ride the session natively** → ideal for the "current tenant" seed. `currentUser()` is a rate-limited Backend API call — use sparingly.
- Client hooks: `useAuth()` (`{ orgId, ... }`), `useUser()`, `useOrganization()` (`{ organization, membership }`), `useOrganizationList()` (`{ userMemberships:{data,hasNextPage,...}, createOrganization, setActive }`). `createOrganization({ name, slug? })` returns org → `setActive({ organization: id })`.
- **Organizations = multi-tenant** (Slack/Linear-style): user in many orgs, one **Active Organization** per tab; org has `id, name, slug, createdBy, createdAt, imageUrl`. Multiple tabs share the session-cookie org — for background fetches use `getToken()` + `Authorization` header (session cookie is a singleton); note for multi-tenant correctness.
- **Webhooks** (App Router): `verifyWebhook` from `@clerk/nextjs/webhooks` in a `POST /api/webhooks` route; events `user.created/updated`, `organization.created/updated/deleted`, `organizationMembership.created/updated/deleted`. Local dev: `npx clerk@latest webhooks listen --forward-to http://localhost:3000/api/webhooks` (tunnel/subprocess). Matcher must keep `/api/webhooks/**` un-protected.
- **Localization:** `@clerk/localizations` package; **`esES` (and es-MX/es-CR/es-UY) available**; pass `<ClerkProvider localization={esES}>`. Only affects Clerk components (hosted Account Portal stays English).
- **Test mode:** dev instances run in test mode by default (fake emails); verify via `npx clerk@latest api --fapi /environment`. E2E can inject a session JWT/cookie for a seeded Clerk test user.
- **Env vars:** `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, and redirects `NEXT_PUBLIC_CLERK_SIGN_IN_URL` etc.
- **Anonymous/guest sessions:** Clerk's **anonymous/signed-out session support is NOT a reliably documented feature in `@clerk/nextjs` v7** — do not depend on it.

## Recommended Decisions (a–h) with tradeoffs

**a. Tenant model → Clerk Organizations (org = tenant).** 1:1 mapping: `Tenant.id↔org.id`, `name↔org.name`, `slug↔org.slug`, `ownerUserId↔org.createdBy` (creator id), `createdAt↔org.createdAt`. `listTenantsForUser ↔ organizations.getOrganizationMembershipList({userId})`; `switchTenant ↔ setActive({organization})` / `orgId` in session; current tenant = `auth().orgId`. Free membership, roles (admin/member → drives `TenantMember` later), invitations. *Alternative (custom Tenant in `publicMetadata`) rejected:* parallel entity + webhook sync + drift, and loses org primitives.
**b. Guest support → DROP.** Clerk lacks a dependable guest/anonymous session. Signed-out `/chat` already shows the `loginToSave` experience; guests were already gated from tenant creation in the blueprint. Remove `createGuestUser`, the guest provider, `guestRegex`, `/api/auth/guest`, and the guest branch in `sidebar-user-nav`. *Alternative (local anon user not Clerk-managed) rejected:* two identity systems, confusing. Drop = least surface, aligns with Clerk reality. **Flag to user for confirmation in proposal** (product behavior change).
**c. Port mapping to Clerk:**
- `getUserByEmail(email)` → `clerkClient.users.getUserList({ emailAddress:[email] })` (Backend API) → `AuthUser` (or `null`). Also serves the register `user_exists` guard.
- `createUser(email, password)` → **obsolete for Clerk mode** (sign-up is client-side via Clerk). Adapter returns a port-shaped user or throws `not-implemented`; register flow moves to Clerk SignUp.
- `createGuestUser()` → removed (see b).
- `verifyCredentials(email, password)` → **obsolete** (Clerk verifies). Could map to `users.verifyPassword({userId,password})` but UI never calls it post-sign-in. Mark obsolete in Clerk adapter.
- `getTenantById(tenantId)` → `organizations.getOrganization({organizationId})` → `Tenant`.
- `getTenantByUser(userId, tenantId)` → session `orgId` (+ membership membership check) → `getOrganization`; if `orgId !== tenantId`, return null.
- `createTenant(userId, name)` → `organizations.createOrganization({ name, createdBy: userId })` (server-side via adapter keeps the port pure); client path `useOrganizationList().createOrganization` also exists.
- `listTenantsForUser(userId)` → `users.getOrganizationMembershipList({ userId })` → map memberships to `Tenant[]`.
**d. Session layer → REPLACE NextAuth entirely (no coexistence).** Two session cookies (`next-auth.session-token` + `__session`) and two auth states to reconcile is strictly worse. The port+provider seam from the blueprint isolates this: swap the seed source (`NextAuth auth()` → Clerk `auth()`) and the adapter; the **UI (`useAuth()`) is untouched**. Recommend folding session resolution into a tiny per-mode seam (Clerk `auth()` for clerk, NextAuth `auth()` for in-memory) so the port stays vendor-agnostic.
**e. User/org sync → ON-DEMAND in the Clerk adapter (no webhooks for now).** Every port call hits the Clerk Backend API (`clerkClient`) / session claims; no local `User` projection from webhooks. Rationale: no real DB yet (mock file store — webhook writes there are dead-end), dev/E2E webhook reachability is flaky (`clerk webhooks listen` subprocess), and it keeps the app functional when webhook delivery lags. Document a production webhook route (`/api/webhooks` + `verifyWebhook`) as a later step. Chats/docs stay local, keyed by stable Clerk `user_*` ids.
**f. UI → PREBUILT Clerk `<SignIn/>`/`<SignUp/>` on the auth pages + port/`useAuth()` untouched in the panel.** Prebuilt = fast, full flows (forgot password, MFA, OAuth), localized via `@clerk/localizations` `esES`, `appearance` themed to match shadcn. Only server-side tenant/user data reads the port (panel). *Alternative (custom forms via `useSignIn/useSignUp`) rejected:* reimplements flows + error handling + manual es copy, high effort. Consequence: `t.auth.*` copy on `/login`,`/register` is replaced by Clerk esES strings → **existing `auth.test.ts` Spanish assertions must be reworked.**
**g. Mock users → WIPE on migration.** Mock users/passwords can't be carried to Clerk (Clerk owns hashing + sign-up). They're dev-only; clear `users` in the mock store (and accept orphaned chats, or clear all) before enabling clerk adapter. **Flag:** if real data exists in `.data/db.json`, export first.
**h. E2E → two layers.** (1) **Deterministic** UI/tenant E2E against `AUTH_ADAPTER=in-memory` (existing pattern, no Clerk dependency). (2) **Focused Clerk smoke suite** (test mode): sign-in, register, org create/switch — Seed a Clerk test user + inject a session JWT cookie in Playwright (`clerkClient` to mint a token), skip-pattern in CI when keys absent.

## Migration Approach

1. **Bump platform first:** `react` 19.0.1 → `~19.1.x` (peer ~19.0.3+), `next` 16.2.0 → `16.2.6+` (GHSA). These are independent, verifiable by `pnpm build`.
2. **Reuse the auth-tenant port/adapters/UI** as the basis (it is already spec'd); in the Clerk change, add the **real `clerk` adapter** (replacing the throw stub) + **session seam** (`Clerk auth()` for clerk mode) + `proxy.ts` (`clerkMiddleware`) + root-layout `ClerkProvider` (swap `SessionProvider`) + prebuilt SignIn/SignUp pages.
3. **Remove NextAuth** (`next-auth`, `bcrypt-ts` only if in-memory adapter is dropped; keep if retained as fallback), delete `auth.ts`/`auth.config.ts`/`[...nextauth]`/guest route.
4. Decide sequencing with the orchestrator: **apply auth-tenant (NextAuth mock-first) then swap**, OR **fold both into one change** the port ships with clerk adapter + in-memory fallback. Folding avoids throwaway NextAuth JWT work; applying-first gives an independently shippable mock baseline + deterministic E2E.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `react` 19.0.1 vs Clerk peer `~19.0.3+` | Bump to 19.1.x, verify `pnpm build` + E2E in an isolated change |
| `next` 16.2.0 GHSA-26hh-7cqf-hhc6 (Middleware bypass) | Bump `next` ≥16.2.6 before adding `proxy.ts` |
| Next 16 boundary file renamed → `proxy.ts` (no middleware today) | Create `proxy.ts` (not `middleware.ts`); Clerk handles both |
| `createRouteMatcher()` deprecated | Use `await auth.protect()` at page/route level, not middleware path matching |
| Two cookie sessions during transition | Remove NextAuth cleanly in same change; `clerkMiddleware` skip old `/api/auth` paths if overlap |
| Hydration / auth-UI flash | Panel seed stays server-side behind Suspense (blueprint); Clerk components have their own loading + `appearance` |
| i18n drift (es) | `@clerk/localizations` `esES` on ClerkProvider; **rework `auth.test.ts` Spanish assertions**; panel copy unchanged |
| E2E determinism | In-memory adapter for full UI suite; Clerk smoke via test user + JWT cookie injection; skip when keys absent |
| Clerk outage / ambient failure | `auth()` reads JWT without network (signed-in users keep working); adapter API failures caught → `ChatbotError` → UI falls back to `noTenants`/signed-out |
| Env/config drift (publishable/secret key at build) | `clerk doctor`/`env pull`; fail fast with clear error; keep keys out of VCS |
| Static metadata / Next 16 ambiguous-metadata | ClerkProvider added to root layout must not force `cookies()` in prerenderable routes — keep existing Suspense/script patterns |