# Apply Progress — Session Telemetry Fixes (P2 — Deletion UX + P3 — Landing light theme)

- **Artifact store**: openspec (repo-local at `openspec/`)
- **Change**: `session-telemetry-fixes`
- **Phase**: 4 — P3 Landing light theme (tasks 4.1–4.2); cumulative through P2 (3.1–3.4)
- **Branch**: `feature/telemetry-ui-fixes` (P1a + P1b + P2 already merged/pushed)
- **Mode**: Standard (openspec `rules.apply.tdd: false`; conflicts with `testing.strict_tdd: true` — see Risks)
- **Delivery strategy**: auto-chain, stacked-to-main — this is the PR 4 slice "P3 landing light theme"

## Prior batches (cumulative state, from git history)

- **P1a — backend telemetry + deletion backend** (PR 1, tasks 1.1–1.11): `agent_sessions` migration `0007` with `conversations.deleted_at`; ORM + `session_tasks.py` (7 consultaarca defaults); port/adapter for agent sessions; `GET /v1/agent-sessions`; `chat.py` `_persist_agent_session` post-run write + tombstoned-upsert refusal; `on_task_metrics` port contract; composio telemetry adapter (Logs/Usage APIs); conversation repo tombstone + PATCH title; DELETE 404; pytest suites (AST/CD, ADR-7 mocked).
- **P1b — frontend consume** (PR 2, tasks 2.1–2.5): BFF `/api/agent-sessions` + typed helper; SWR hook + dashboard page + i18n; 7-label subtask template sync; `/api/messages` activity hydrate; vitest `agent-sessions.test.ts` (7) + e2e reload case.
- **P2 — deletion UX** (PR 3, tasks 3.1–3.4): BFF DELETE 404→`{success:false,deleted:false}`; `patchConversationTitle` (PATCH no-create); sidebar awaited delete + reconcile + invalidation + active-chat navigation + error toast; 12 new vitest cases + 2 signed-in e2e cases.

## Work Unit Evidence

| PR 3 — Deletion UX (tasks 3.1–3.4) | Value |
|---|---|
| Focused test command and exact result | `pnpm test:unit` → 8 files, 66 tests passed (12 new: `conversations.test.ts` 8 + `delete-reconcile.test.ts` 4). `pnpm typecheck` → clean (0 errors). `ultracite check` on changed files → 0 diagnostics |
| Runtime harness command/scenario and exact result | Playwright signed-in project: `e2e/conversation-delete.signedin.spec.ts` — CD-3 (BFF 404 → `{success:false,deleted:false}`) + CD-4 (delete active chat → navigate to `/chat`, row gone, success toast). Listed by `playwright test --list` under the `signed-in` project; not executed here — follows the Clerk-credential skip idiom (no hard failure without `CLERK_SECRET_KEY`/`E2E_CLERK_USER_*`) |
| Rollback boundary | Revert the 4 modified files + delete the 3 new files (`frontend/lib/backend/conversations.test.ts`, `frontend/lib/chat/`, `frontend/tests/e2e/conversation-delete.signedin.spec.ts`). Backend `POST /v1/conversations` still exists (unused by BFF) so reverting to `saveConversation` restores the old POST title save; P1a/P1b slices are untouched |

| PR 4 — Landing light theme (tasks 4.1–4.2) | Value |
|---|---|
| Focused test command and exact result | `pnpm typecheck` → clean, 0 errors. `pnpm test:unit` → 8 files, 66 tests passed (P2 baseline intact, no regression). `ultracite check` on the 4 P3 files → 0 diagnostics (app/(chat)/layout.tsx checked via /tmp copy because Biome's path parser chokes on the `(chat)` parens — tool limitation) |
| Runtime harness command/scenario and exact result | `pnpm exec playwright test tests/e2e/theme-scoping.test.ts tests/e2e/theme-toggle.signedin.spec.ts` → **3 passed, 3 skipped, 0 failed** (24.6s): LLT-1 dark OS + stored dark theme → light, no `.dark` anywhere; LLT-1 light OS → light; LLT-2 no-flash MutationObserver during load → no `.dark` ever seen. Signed-in toggle spec skipped via the Clerk-credential idiom (global setup skips without `CLERK_SECRET_KEY`/`E2E_CLERK_USER_*`) — no hard failure. Full `e2e` project (auth.test.ts 4 + theme-scoping 3) → 7 passed |
| Rollback boundary | Revert `frontend/app/layout.tsx` (root ThemeProvider back in, git restore P2 tip `3af9efb`), remove the scoped provider from `frontend/app/(chat)/layout.tsx`, delete the 2 new e2e files (`tests/e2e/theme-scoping.test.ts`, `tests/e2e/theme-toggle.signedin.spec.ts`). P1a/P1b/P2 slices untouched |

## What was done per task

- [x] **3.1** `frontend/app/(chat)/api/chat/route.ts`:
  - `DELETE`: backend 404 is no longer swallowed as a successful no-op — BFF returns `Response.json({success:false, deleted:false}, {status:404})`; real deletions return `{success:true, deleted:true}` (CD-3).
  - Title save switched from `saveConversation` (POST upsert) to `patchConversationTitle` (PATCH title-only, never creates); a deleted chat logs "title not saved" instead of resurrecting a row (CD-2).
- [x] **3.2** `frontend/lib/backend/conversations.ts`:
  - `deleteConversation` → `Promise<{deleted:boolean}>`: backend 204 → `{deleted:true}`; backend 404 → `{deleted:false}` (honest failure, no throw); other statuses rethrow `BackendError`.
  - New `patchConversationTitle(id, title)` → `Promise<{ok:boolean}>`: PATCH with `{title}`; 404 → `{ok:false}`; other failures rethrow.
  - New `DeleteChatResponse` + `buildDeleteChatResponse(deleted)` — pure BFF DELETE envelope builder so the CD-3 contract is unit-testable.
  - Removed `saveConversation`/`SaveConversationInput` (dead POST path; only caller was the BFF route). `deleteAllConversations`/`listConversations`/`getConversation` untouched.
- [x] **3.3** `frontend/components/chat/sidebar-history.tsx`:
  - `handleDelete` is now async and AWAITS the BFF DELETE (no more fire-and-forget fetch + unconditional success toast).
  - Success: optimistic removal via `reconcileChatsAfterDelete` + SWR revalidation (invalidation); success toast; if the deleted chat is the ACTIVE chat (`id === chatToDelete`) it navigates to `/chat` (app Home).
  - Failure (HTTP error, `success/deleted !== true` envelope, network exception): the row is NEVER dropped — `await mutate()` revalidates to server truth and a visible error toast is shown (new i18n key `chatDeletedError` in `en` + `es`).
  - New pure helper `frontend/lib/chat/delete-reconcile.ts` (generic, React-free) so the reconcile contract is unit-testable.
- [x] **3.4** Tests (same unit as the behavior):
  - `frontend/lib/backend/conversations.test.ts` (8 tests): `deleteConversation` 204→`{deleted:true}` / 404→`{deleted:false}` / 5xx rethrows (CD-3); `patchConversationTitle` PATCH body+method, 404→`{ok:false}` never resurrects (CD-2), 5xx rethrows; `buildDeleteChatResponse` honest envelope (CD-3). `callBackend` mocked via `vi.hoisted`/`vi.mock`, real `BackendError` kept via `importOriginal`.
  - `frontend/lib/chat/delete-reconcile.test.ts` (4 tests): removes row across every page, preserves `hasMore`, no-op on null/missing id (CD-4).
  - `frontend/tests/e2e/conversation-delete.signedin.spec.ts` (2 tests, named for the `signed-in` Playwright project + Clerk-credential skip idiom): CD-3 BFF 404 propagation via `page.request.delete` (asserts status 404 + `{success:false, deleted:false}`); CD-4 full UI flow (run consultaarca → delete active chat via sidebar kebab → navigates to `/chat`, row gone, success toast).

## What was done per task (P3)

- [x] **4.1** `frontend/app/layout.tsx` + `frontend/app/(chat)/layout.tsx` (partial work from the interrupted session verified, completed):
  - Root `ThemeProvider` REMOVED from `app/layout.tsx` — the head scripts (`THEME_COLOR_SCRIPT`, `LOCALE_SCRIPT`) and `LanguageProvider`/`ClerkLocaleProvider`/`TooltipProvider` stay; root never sets a theme class (LLT-1/3).
  - Scoped `<ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>` in `(chat)/layout.tsx` wraps `SidebarShell` (inside `DataStreamProvider`); only `useTheme` consumers (`sidebar-user-nav`, `sheet-editor`) are chat-scoped, so nothing outside the chat shell needs the provider.
  - Verified by probe on the real landing under dark OS emulation: `htmlHasDark:false`, `.dark` count 0 — the `@custom-variant dark` never matches on landing; the legacy `@media (prefers-color-scheme: dark)` block in globals.css L234 only rewrites dead `--*-rgb` vars (used nowhere else in the codebase), so it does not affect semantic tokens.
- [x] **4.2** E2E (2 new files):
  - `tests/e2e/theme-scoping.test.ts` (3 tests, `e2e` project): LLT-1 dark OS + stored `theme=dark` in localStorage → landing light, no `.dark` on html or any element, body luminance light; LLT-1 light OS → same; LLT-2 no-flash — an init MutationObserver watches `<html>` class from document start and never observes `.dark` during load/hydration.
  - `tests/e2e/theme-toggle.signedin.spec.ts` (2 tests, `signed-in` project + Clerk skip idiom): LLT-3 toggle dark in chat → `html.dark` appears; revisit landing → light, no `.dark`; toggle back to light → `html.dark` removed. Listed and skipped cleanly without creds (global setup skip idiom — no hard failure).
  - **Root cause fixed** (the one failing case): the original luminance helper only understood `rgb()`; Chromium serializes the computed `background-color` of the oklch token as `lab(98.26 0 0)` (Lab L in 0..100), so the helper treated L=98.26 as an sRGB channel → `98.26*0.2126/255 = 0.0819` — below the 0.9 threshold, failing a LIGHT background. Helper now handles `lab()`/`oklch()` (L as the perceptual-luminance proxy) and falls back to the sRGB-weighted rgb() formula. The theme scoping itself was already correct — only the assertion parser was wrong.

## Files changed

| File | Action | What was done |
|---|---|---|
| `frontend/app/(chat)/api/chat/route.ts` | Modified | DELETE envelope 404→`{success:false,deleted:false}`; title save POST→PATCH |
| `frontend/lib/backend/conversations.ts` | Modified | `deleteConversation` deleted-flag contract; `patchConversationTitle`; `buildDeleteChatResponse`; removed POST `saveConversation` |
| `frontend/components/chat/sidebar-history.tsx` | Modified | awaited DELETE, honest success/failure handling, reconcile+invalidate, active-chat navigation |
| `frontend/i18n/dictionary.ts` | Modified | `chatDeletedError` key (en + es) |
| `frontend/lib/chat/delete-reconcile.ts` | Created | Pure CD-4 reconcile helper (React-free, generic) |
| `frontend/lib/backend/conversations.test.ts` | Created | 8 vitest cases (CD-2/3) |
| `frontend/lib/chat/delete-reconcile.test.ts` | Created | 4 vitest cases (CD-4) |
| `frontend/tests/e2e/conversation-delete.signedin.spec.ts` | Created | 2 e2e tests (CD-3/4), signed-in project + skip idiom |

### P3 files

| File | Action | What was done |
|---|---|---|
| `frontend/app/layout.tsx` | Modified | Removed root `<ThemeProvider>`; head scripts + Language/Clerk/Tooltip providers intact; root never sets a theme class (LLT-1/3) |
| `frontend/app/(chat)/layout.tsx` | Modified | Scoped `<ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>` around `SidebarShell` (LLT-1/3) |
| `frontend/tests/e2e/theme-scoping.test.ts` | Created | 3 e2e tests: LLT-1 dark OS + stored theme → light, LLT-1 light OS → light, LLT-2 no `.dark` during load (MutationObserver). Luminance helper handles Chromium's `lab()`/`oklch()` color serialization |
| `frontend/tests/e2e/theme-toggle.signedin.spec.ts` | Created | 2 e2e tests: LLT-3 chat toggle dark/light works, landing stays light on revisit; signed-in project + Clerk-credential skip idiom |

## Remaining tasks

- None for this change — tasks 4.1/4.2 complete. All PR-slice tasks (1.1–4.2) are implemented; P1a/P1b/P2 are merged/pushed, P3 is in the working tree awaiting the orchestrator's work-unit commits. `tasks.md` P1a/P1b checkboxes (1.1–2.5) remain stale `- [ ]` from prior batches (flagged across batches).

## Workload / PR boundary

- Mode: chained PR slice (stacked-to-main) — "P2 deletion UX" (PR 3) and "P3 landing light theme" (PR 4)
- Boundary (P2): starts with the P1b tip (`7902d11` docs-layout commit `5b11678`) and ends at tasks 3.1–3.4 complete; does NOT touch P3 (theme) or other changes
- Boundary (P3): starts with the P2 tip (`3af9efb`) and ends at tasks 4.1–4.2 complete; touches ONLY the 2 layouts + 2 new e2e files (~260 lines incl. tests) — within the 400-line budget for this slice
- Estimated review budget impact: P2 ~198 changed lines; P3 ~260 changed lines (2 modified + 2 created files) — each slice stays within the 400-line budget
- Commits are NOT created by the executor per the launch contract; changes are left in the working tree for the orchestrator

## Risks

- `openspec/config.yaml` is internally inconsistent: `testing.strict_tdd: true` vs `rules.apply.tdd: false`. Resolved as **Standard Mode** (the apply-phase rule wins, consistent with P1b's batch which produced plain vitest files). Recommend sdd-init/orchestrator aligns the config.
- `tasks.md` still shows P1a/P1b tasks 1.1–2.5 with `- [ ]` checkboxes even though those batches are implemented and pushed (previous batches did not update checkboxes). Flagged for the orchestrator; this batch only checked its own scope (3.1–4.2).
- Design deviation (P2): `design.md` sequence diagram says active-chat navigation is `router push "/"`, but `/` is the marketing landing outside the chat shell; implemented `router.push("/chat")` (the app Home per `app-sidebar.tsx` Home link `/chat`) — navigating to `/` would drop the user out of the app.
- P3 gotcha (discovery, now encoded in the test): Chromium serializes computed custom-property colors in their native color space — the oklch light token comes back as `lab(98.26 0 0)` (Lab L in 0..100), NOT rgb(). Any future luminance/contrast assertion must handle `lab()`/`oklch()` L directly or it will misread a light background as dark.
- P3 environment: disk was 100% full during the first Playwright run (ENOSPC while writing trace artifacts) — freed by removing `frontend/.next` (regenerable build cache). Biome/ultracite cannot lint `app/(chat)/layout.tsx` directly (parenthesized path segment breaks its path parser) — checked via a /tmp copy instead.
- `frontend/tests/e2e/agent-sessions.spec.ts` (P1b) does not match any Playwright project `testMatch` (`e2e/.*.test.ts` or `e2e/.*\.signedin\.spec\.ts`); it silently never runs. P2/P3 specs use the signed-in/`*.test.ts` patterns so they are actually collected.
- Pre-existing lint errors exist repo-wide (70 diagnostics) — none in files touched by this batch.