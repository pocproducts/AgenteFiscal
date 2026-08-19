# Apply Progress — Session Telemetry Fixes (P2 — Deletion UX)

- **Artifact store**: openspec (repo-local at `openspec/`)
- **Change**: `session-telemetry-fixes`
- **Phase**: 3 — P2 Deletion UX (tasks 3.1–3.4)
- **Branch**: `feature/telemetry-ui-fixes` (P1a + P1b already merged/pushed)
- **Mode**: Standard (openspec `rules.apply.tdd: false`; conflicts with `testing.strict_tdd: true` — see Risks)
- **Delivery strategy**: auto-chain, stacked-to-main — this is PR 3 slice "P2 deletion UX"

## Prior batches (cumulative state, from git history)

- **P1a — backend telemetry + deletion backend** (PR 1, tasks 1.1–1.11): `agent_sessions` migration `0007` with `conversations.deleted_at`; ORM + `session_tasks.py` (7 consultaarca defaults); port/adapter for agent sessions; `GET /v1/agent-sessions`; `chat.py` `_persist_agent_session` post-run write + tombstoned-upsert refusal; `on_task_metrics` port contract; composio telemetry adapter (Logs/Usage APIs); conversation repo tombstone + PATCH title; DELETE 404; pytest suites (AST/CD, ADR-7 mocked).
- **P1b — frontend consume** (PR 2, tasks 2.1–2.5): BFF `/api/agent-sessions` + typed helper; SWR hook + dashboard page + i18n; 7-label subtask template sync; `/api/messages` activity hydrate; vitest `agent-sessions.test.ts` (7) + e2e reload case.

## Work Unit Evidence

| PR 3 — Deletion UX (tasks 3.1–3.4) | Value |
|---|---|
| Focused test command and exact result | `pnpm test:unit` → 8 files, 66 tests passed (12 new: `conversations.test.ts` 8 + `delete-reconcile.test.ts` 4). `pnpm typecheck` → clean (0 errors). `ultracite check` on changed files → 0 diagnostics |
| Runtime harness command/scenario and exact result | Playwright signed-in project: `e2e/conversation-delete.signedin.spec.ts` — CD-3 (BFF 404 → `{success:false,deleted:false}`) + CD-4 (delete active chat → navigate to `/chat`, row gone, success toast). Listed by `playwright test --list` under the `signed-in` project; not executed here — follows the Clerk-credential skip idiom (no hard failure without `CLERK_SECRET_KEY`/`E2E_CLERK_USER_*`) |
| Rollback boundary | Revert the 4 modified files + delete the 3 new files (`frontend/lib/backend/conversations.test.ts`, `frontend/lib/chat/`, `frontend/tests/e2e/conversation-delete.signedin.spec.ts`). Backend `POST /v1/conversations` still exists (unused by BFF) so reverting to `saveConversation` restores the old POST title save; P1a/P1b slices are untouched |

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

## Remaining tasks

- [ ] 4.1 `frontend/app/layout.tsx`: remove ThemeProvider; `(chat)/layout.tsx`: scoped provider (P3)
- [ ] 4.2 E2E: landing light, chat toggle, no-flash (P3)

## Workload / PR boundary

- Mode: chained PR slice (stacked-to-main) — "P2 deletion UX"
- Boundary: starts with the P1b tip (`7902d11` docs-layout commit `5b11678`) and ends at tasks 3.1–3.4 complete; does NOT touch P3 (theme) or other changes
- Estimated review budget impact: ~198 changed lines (137 insertions + 61 deletions across 4 modified files; 3 new files ~250 lines incl. tests) — within the 400-line budget for this slice
- Commits are NOT created by the executor per the launch contract; changes are left in the working tree for the orchestrator

## Risks

- `openspec/config.yaml` is internally inconsistent: `testing.strict_tdd: true` vs `rules.apply.tdd: false`. Resolved as **Standard Mode** (the apply-phase rule wins, consistent with P1b's batch which produced plain vitest files). Recommend sdd-init/orchestrator aligns the config.
- `tasks.md` still shows P1a/P1b tasks 1.1–2.5 with `- [ ]` checkboxes even though those batches are implemented and pushed (previous batches did not update checkboxes). Flagged for the orchestrator; this batch only checked its own scope (3.1–3.4).
- Design deviation: `design.md` sequence diagram says active-chat navigation is `router push "/"`, but `/` is the marketing landing outside the chat shell; implemented `router.push("/chat")` (the app Home per `app-sidebar.tsx` Home link `/chat`) — navigating to `/` would drop the user out of the app (the "old bug" the orchestrator flagged).
- `frontend/tests/e2e/agent-sessions.spec.ts` (P1b) does not match any Playwright project `testMatch` (`e2e/.*.test.ts` or `e2e/.*\.signedin\.spec\.ts`); it silently never runs. New spec uses the signed-in pattern so P2 e2e is actually collected.
- Pre-existing lint errors exist repo-wide (70 diagnostics) — none in files touched by this batch.