# Archive Report — session-telemetry-fixes

**Archived at**: 2026-08-19
**Mode**: Automatic · OpenSpec (repo-local at `openspec/`)
**Archive path**: `openspec/changes/archive/2026-08-19-session-telemetry-fixes/`
**Closure type**: COMPLETED — implemented, verified, delivered (P1a/P1b/P2/P3 chained PR slices, branch `feature/telemetry-ui-fixes` tip `04acd2c`)
**Final verify verdict**: `pass_with_warnings` (`gentle-ai.verify-result/v1` envelope, evidence_revision `sha256:923f70ac…fae5c`)

## Gate State at Archive

| Gate | State | Evidence |
|------|-------|----------|
| Native review receipt | ✅ `delivery: disabled/unmanaged` — no review subsystem artifacts exist for this change (`reviewPolicy/Ledger/Receipt/Bundle/Context/State` all `missing`); no explicit review artifact failed validation; native dispatcher routes to archive with zero blockers | `gentle-ai sdd-status session-telemetry-fixes --json` → `dependencies.archive: ready`, `nextRecommended: archive`, `blockedReasons: []` |
| Task completion | ✅ Pass — 22/22 implementation tasks checked `[x]` in persisted `tasks.md` (final state, committed `04acd2c`); native status `taskProgress: {total: 22, completed: 22, allComplete: true}` | `tasks.md`, `gentle-ai sdd-status` |
| CRITICAL findings | ✅ None | `verify-report.md` `critical_findings: 0` |
| Action context | ✅ `mode: repo-local`, allowedEditRoots = repo root; archive ops stayed inside | `sdd-status` `actionContext` |

No stale-checkbox reconciliation was needed: the persisted `tasks.md` already reflects the final state (all `[x]`). The apply-progress note about stale P1a/P1b checkboxes was an intermediate snapshot from apply time; the final apply batch synced them (commit `04acd2c`).

## Specs Synced to Main Tree

The repo has no pre-existing `openspec/specs/` tree (proposal: "`openspec/specs/` empty"; `git log --all -- openspec/specs` empty). The three delta specs are standalone full specifications (no ADDED/MODIFIED/REMOVED/RENAMED delta sections), so per the archive flow each was copied directly into the main specs tree:

| Domain | Action | Requirements | File |
|--------|--------|--------------|------|
| agent-session-telemetry | Created (full spec) | 6 (AST-1..6) | `openspec/specs/agent-session-telemetry/spec.md` |
| conversation-deletion | Created (full spec) | 4 (CD-1..4) | `openspec/specs/conversation-deletion/spec.md` |
| landing-light-theme | Created (full spec) | 3 (LLT-1..3) | `openspec/specs/landing-light-theme/spec.md` |

**Destructive deltas**: NONE. No REMOVED or RENAMED requirements; no existing main specs were modified — the merge was purely additive creation. Nothing was destructively merged, so no confirm-before-merge was required, and no existing requirement was deleted or renamed with (Reason/Migration) notes needed.

## What Was Shipped (final state at close)

- **AST-1** migration `0007` (`agent_sessions` + `conversations.deleted_at`), reversible, down_rev `0006`, single head; AgentSession ORM; all columns nullable/defaulted.
- **AST-3** `domain/session_tasks.py` `DEFAULT_TASKS_BY_TOOL` — 7 consultaarca defaults + `build_session_tasks`; frontend `SUBTASK_TEMPLATES.consultaarca` 7 labels synced.
- **AST-1/2/6** agent-sessions port/adapter (`ports/agent_sessions.py`, `adapters/db_agent_sessions.py` record/list_for) + `GET /v1/agent-sessions?conversation_id=&limit=` tenant/user scoped; BFF `/api/agent-sessions` + SWR hook + agent-sessions page ("Acciones" column, `—` NULLs, i18n).
- **AST-2/6** chat.py `_persist_agent_session` best-effort post-run write in `_run_tool` (`chat.py:1778`), `started_at` pre-dispatch, tombstoned-upsert refusal; `/api/messages` hydrate uses persisted rows (`activity: toAgentSessionSnapshots(rows)`).
- **AST-5** `ports/browser.py` `run_single` declares `on_task_metrics`; composio.py + mock.py accept+ignore; TypeError eliminated.
- **ADR-7 / AST-4** `composio_telemetry.py` Logs API `session_id` + Usage API `event_count`, best-effort; metrics holder feeds session_id; flag: browserbase rows take provider `cost_cents` when present (see WARNING-1).
- **CD-1/2** conversation repo delete→tombstone (`deleted_at`), filters exclude deleted, upsert returns None for tombstoned, `patch_conversation_title`; DELETE 404 for missing/already-deleted; PATCH title-only; BFF PATCH `patchConversationTitle` (POST `saveConversation` removed).
- **CD-3** BFF DELETE honest envelope: 204→`{success:true,deleted:true}`, 404→`{success:false,deleted:false}` (chat route:616–638).
- **CD-4** sidebar-history async awaited DELETE; success → reconcile + SWR invalidation + navigate `/chat` when active + success toast; failure → reconcile to server truth + `chatDeletedError` toast (en/es).
- **LLT-1/3** root ThemeProvider removed from `app/layout.tsx` (head scripts + Language/Clerk/Tooltip stay); scoped `<ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>` in `(chat)/layout.tsx` around SidebarShell; landing never gets `.dark` (`@custom-variant dark` never matches); build prerenders `/` static.
- **LLT-2** no-flash e2e (MutationObserver from document start); luminance helper handles Chromium `lab()`/`oklch()` serialization.

## Final Verification Evidence (at close)

| Suite | Result |
|-------|--------|
| Backend focused pytest (`test_agent_sessions.py` + `test_conversation_deletion.py` + `test_chat_stream.py`) | ✅ 30 passed, exit 0 |
| Full repo backend suite (all `agente_fiscal/tests/`) | ⚠️ 296 passed + **44 failed** — ALL pre-existing drift in files with zero overlap with this change (see WARNING-2) |
| `pnpm test:unit` | ✅ 8 files, 66 passed, exit 0 |
| `pnpm typecheck` (tsc --noEmit) | ✅ 0 errors |
| Theme e2e (`theme-scoping.test.ts` + `theme-toggle.signedin.spec.ts`) | ✅ 3 passed, 3 skipped (Clerk-credential skip idiom), 0 failed |
| `pnpm build` | ✅ OK (70s, exit 0) |
| Alembic AST-1 migration | ✅ upgrade 0006→0007 + downgrade 0006 clean on scratch DB, 15 columns verified |

**Spec compliance (final)**: 13/13 requirements with evidence; 16/23 scenarios fully runtime-asserted (✅ COMPLIANT); 7/23 ⚠️ PARTIAL — all with passing covering tests at lower layers plus source inspection, or repo-sanctioned skips (Clerk creds absent; `agent-sessions.spec.ts` not collected — pre-existing Playwright `testMatch` gap); 0 UNTESTED, 0 FAILING, 0 CRITICAL.

## Open Warnings (recorded, not fixed — orchestrator handoff)

1. **WARNING-1 — AST-4 cost-literal deviation** (verified, expected): `backend/agente_fiscal/api/routes/chat.py:1749` writes the provider `cost_cents` onto browserbase rows when the metrics payload carries it, while the spec/design literal say `cost_cents = 0` (proposal lists non-zero cost out of scope). Engine/composio/mock rows are always 0. Best-effort behavior; classified WARNING not defect — future decision: spec amendment (real cost is arguably better) or clamp to 0.
2. **WARNING-2 — 44 pre-existing backend failures**: confined to `test_report_approval` (17), `test_report_runs_api` (13), `test_report_runner` (12), `test_features` (1), `test_clients_api` (1); root cause `report_runs.profile_id NOT NULL` vs tests inserting NULL (schema/model drift). Zero overlap with this change; separate remediation ticket.
3. **WARNING-3 — optional test polish**: 7 PARTIAL scenarios lack a direct runtime assertion of the final hop (HTTP-level route test for `GET /v1/agent-sessions`, row assert in browser `_run_tool` cases, reload e2e collection, signed-in toggle execution). Tracked as SUGGESTION items in verify-report, not re-apply work.

## Artifacts in Archive

| Artifact | Status |
|----------|--------|
| exploration.md / exploration-extra.md | preserved (historical) |
| proposal.md | preserved |
| specs/ (agent-session-telemetry, conversation-deletion, landing-light-theme) | preserved + synced to main tree |
| design.md | preserved (ADR-1..7 documented) |
| tasks.md | preserved — 22/22 `[x]`, no unchecked implementation tasks |
| apply-progress.md | preserved (historical intermediate snapshots) |
| verify-report.md | preserved (final, `pass_with_warnings`) |
| archive-report.md | ✅ this file |

Active `openspec/changes/session-telemetry-fixes/` moved to `openspec/changes/archive/2026-08-19-session-telemetry-fixes/`; active changes directory no longer lists this change. No commits or pushes created (per launch contract — tree state left for the orchestrator).

## Notes

- **Design deviation (documented, verified)**: design sequence diagram said active-chat navigation `router.push("/")`; implemented `router.push("/chat")` (app Home; `/` is the marketing landing — matches proposal intent "stay in app"). Already flagged in apply-progress.
- **Config inconsistency (pre-existing)**: `openspec/config.yaml` `testing.strict_tdd: true` vs `rules.apply.tdd: false` — resolved as Standard Mode for this change; sdd-init reconciliation recommended.
- **Provenance**: archive facts ranked per Final-State Authority — native status + orchestrator final-state handoff (+ persisted verify-report) used for close-state numbers; earlier apply-progress/verify warnings were cross-checked and attributed to their intermediate time.

## SDD Cycle Complete

The change has been fully planned, implemented, verified, and archived. Ready for the next change.