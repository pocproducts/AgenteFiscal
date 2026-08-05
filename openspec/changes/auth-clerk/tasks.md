# Tasks: Auth Clerk & Folder Restructure (Clean & Hexagonal)

## Phase 1: Directory Restructuring & tsconfig Setup

- [ ] 1.1 Create `backend/` and `frontend/` directories at the project root.
- [ ] 1.2 Move database submodules:
  - Create `backend/db/`
  - Move `lib/db/schema.ts` -> `backend/db/schema.ts`
  - Move `lib/db/queries.ts` -> `backend/db/queries.ts`
- [ ] 1.3 Move AI submodules:
  - Move `lib/ai/` -> `backend/ai/`
- [ ] 1.4 Move artifacts submodules:
  - Move `lib/artifacts/` -> `backend/artifacts/`
- [ ] 1.5 Move frontend components & hooks:
  - Move `components/` -> `frontend/components/`
  - Move `hooks/` -> `frontend/hooks/`
- [ ] 1.6 Move other frontend submodules:
  - Move `lib/i18n/` -> `frontend/i18n/`
  - Move `lib/editor/` -> `frontend/editor/`
- [ ] 1.7 Update `tsconfig.json` paths to map legacy paths dynamically (avoiding manual import updates for unchanged files):
  - Map `@/components/*` -> `./frontend/components/*`
  - Map `@/hooks/*` -> `./frontend/hooks/*`
  - Map `@/lib/db/*` -> `./backend/db/*`
  - Map `@/lib/ai/*` -> `./backend/ai/*`
  - Map `@/lib/artifacts/*` -> `./backend/artifacts/*`
  - Map `@/lib/i18n/*` -> `./frontend/i18n/*`
  - Map `@/lib/editor/*` -> `./frontend/editor/*`
  - Add `@/backend/*` -> `./backend/*` and `@/frontend/*` -> `./frontend/*`

---

## Phase 2: Hexagonal Backend Auth (`backend/auth`)

- [ ] 2.1 Create folder structure:
  - `backend/auth/`
  - `backend/auth/domain/entities/`
  - `backend/auth/domain/ports/`
  - `backend/auth/infrastructure/adapters/`
- [ ] 2.2 Create `backend/auth/domain/ports/auth.port.ts` containing the `AuthUser`, `Tenant`, and `AuthPort` interfaces.
- [ ] 2.3 Create `backend/auth/infrastructure/adapters/in-memory-auth.adapter.ts` implementing `AuthPort` using `backend/db/queries.ts`.
- [ ] 2.4 Create `backend/auth/infrastructure/adapters/clerk-auth.adapter.ts` implementing `AuthPort` calling Clerk Backend API (`clerkClient`).
- [ ] 2.5 Create `backend/auth/infrastructure/adapters/auth.factory.ts` to switch adapters dynamically based on the `AUTH_ADAPTER` env var.

---

## Phase 3: Clean Frontend Auth presentation

- [ ] 3.1 Create `frontend/auth/presentation/context/auth.context.tsx` with React context `AuthProvider`.
- [ ] 3.2 Create `frontend/auth/presentation/hooks/use-auth.ts` containing the `useAuth()` hook.
- [ ] 3.3 Ensure the context abstracts the mode (InMemory vs Clerk).
- [ ] 3.4 Update App Sidebar user navigation and Chat header components to use `useAuth()`.

---

## Phase 4: Clerk SDK Integration & NextAuth Removal

- [ ] 4.1 Install Clerk packages: `@clerk/nextjs` and `@clerk/localizations`.
- [ ] 4.2 Uninstall `next-auth` and `bcrypt-ts` from `package.json`.
- [ ] 4.3 Update `app/layout.tsx` to wrap the app with `ClerkProvider` using `esES` (Spanish localization) and the dark/light appearance tokens.
- [ ] 4.4 Create root `/proxy.ts` middleware configured with `clerkMiddleware` to protect `/chat` routes.
- [ ] 4.5 Replace auth pages:
  - Replace `app/(auth)/login/page.tsx` with Clerk's `<SignIn />` component.
  - Replace `app/(auth)/register/page.tsx` with Clerk's `<SignUp />` component.
- [ ] 4.6 Delete obsolete files:
  - `app/(auth)/auth.ts`
  - `app/(auth)/auth.config.ts`
  - `app/(auth)/api/auth/[...nextauth]/route.ts`
  - `app/(auth)/api/auth/guest/route.ts`

---

## Phase 5: Verification & Compilation

- [ ] 5.1 Run check / lint commands to verify no typescript/compiler errors.
- [ ] 5.2 Validate application build using `npm run build`.
