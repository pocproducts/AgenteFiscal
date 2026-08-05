# Proposal: Clerk Migration for Register/Login/Tenant

## Intent

Replace NextAuth v5 with Clerk (first real identity migration) behind the existing hexagonal `AuthPort`. Real sign-up/login/tenant on Clerk; UI untouched; no throwaway NextAuth session work.

## Scope

### In Scope
- Platform bump: `react` 19.0.1→`~19.1.x`, `next` 16.2.0→`16.2.6+` (GHSA-26hh-7cqf-hhc6) — prerequisite.
- Hexagon: `lib/auth/port.ts` (8 methods; `AuthUser`/`Tenant`/`AuthSeed`), `adapters/{in-memory,clerk}.ts`, factory `getAuthAdapter()` (`AUTH_ADAPTER`).
- Remove NextAuth v5; per-mode session seam (`clerk auth()` | NextAuth-style for in-memory). UI consumes only `useAuth()`.
- Clerk: `ClerkProvider` (root layout), prebuilt `<SignIn/>`/`<SignUp/>` (esES + appearance), `proxy.ts` with `auth.protect()`, org=tenant.
- E2E: deterministic in-memory suite + Clerk smoke (skipped without keys).

### Out of Scope
Webhooks; real DB/backend; chat-data migration; billing/permissions beyond owner; identity sync beyond on-demand adapter calls.

## Capabilities

> Contract with sdd-spec. `openspec/specs/` empty → all new full specs; auth-tenant deltas absorbed.

### New Capabilities
- `auth-core`: port + in-memory adapter + `AuthProvider`/`useAuth()` + server seed behind Suspense.
- `tenant`: Clerk Organizations⇄Tenant mapping; create/switch/list/current.
- `clerk-auth`: ClerkProvider, prebuilt SignIn/SignUp (esES), `proxy.ts` protection, real clerk adapter, session seam, platform bump.

### Modified Capabilities
- None.

## Approach

1. Bump platform; verify build. 2. Reuse auth-tenant port/adapters/UI (**folding** — supersedes auth-tenant; its NextAuth JWT work is discarded). 3. Real `clerk.ts` adapter (`clerkClient`, on-demand, no webhooks) + session seam. 4. `ClerkProvider` in root layout; prebuilt auth pages; `proxy.ts` (all-public default, `auth.protect()` on `/chat`). 5. Wipe mock users. 6. Rework `tests/e2e/auth.test.ts`. 7. Remove NextAuth/`bcrypt-ts`/`auth.ts`/`auth.config.ts`/`[...nextauth]`/guest route.

## Product decisions — need confirmation

| Flag | Change | Reason |
|------|--------|--------|
| Guest flow | **Drop** guest provider/`guestRegex` | Clerk lacks reliable guest session; `/chat` signed-out shows `loginToSave` |
| Auth forms | **Replace** custom forms with prebuilt SignIn/SignUp (esES) | Full flows/MFA/OAuth; `t.auth.*` replaced |
| Mock data | **Wipe** mock users (dev-only) | Clerk owns sign-up; orphaned chats accepted |

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `package.json` | Modified | add Clerk deps; bump react/next; drop next-auth/bcrypt-ts |
| `lib/auth/**` | New/Modified | port, adapters, provider |
| `app/(auth)/**` | Mod/Removed | delete auth.ts/config.ts/routes; Clerk pages |
| `app/layout.tsx` | Modified | ClerkProvider over SessionProvider |
| `proxy.ts` | New | clerkMiddleware + auth.protect() |
| `app/(chat)/**` | Modified | clerk auth() seed; drop user prop-drill |
| `lib/i18n/dictionary.ts` | Modified | `panel.tenant.*` en/es |
| `tests/e2e/auth.test.ts` | Modified | tenant E2E + Clerk smoke |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Platform bump breaks build | Med | Isolate bump, verify build |
| Two cookies transition | Med | Remove NextAuth in same change; matcher skips `/api/auth` |
| Adapter/port drift | Med | Adapters import port types |
| E2E flaky w/o Clerk keys | Med | In-memory for UI suite; smoke skips |
| Product flags (guest/forms/wipe) | Med | Flagged above; ask before apply |

## Rollback Plan

`git revert`. In-memory adapter keeps register/login/tenant working with no Clerk. Clerk org data persists (idempotent re-sync).

## Dependencies

- Clerk dev instance + `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`/`CLERK_SECRET_KEY`.
- `next ≥16.2.6`, `react ~19.1.x`.

## Success Criteria

- [ ] Register/login/tenant on Clerk; panel uses only `useAuth()`, no Clerk/NextAuth imports.
- [ ] Org create/switch reflects in chat; user-run `pnpm build`+`pnpm test` green.
- [ ] Clerk smoke passes with keys; in-memory UI suite passes without.
- [ ] No NextAuth code or guest flow remains.