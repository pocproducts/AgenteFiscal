# Tasks: Session Telemetry Fixes

## Phase 1: P1a — Backend telemetry (PR 1)

- [x] 1.1 `backend/alembic/versions/0007_agent_sessions_deleted_at.py` (down_rev `0006`): `agent_sessions` + `conversations.deleted_at`, reversible (AST-1)
- [x] 1.2 `db/models/business.py`: AgentSession ORM; Conversation.deleted_at (AST-1)
- [x] 1.3 `domain/session_tasks.py`: `DEFAULT_TASKS_BY_TOOL` (7 consultaarca defaults) + `build_session_tasks` (AST-3)
- [x] 1.4 `ports/agent_sessions.py` (pydantic + repo protocol) + `adapters/db_agent_sessions.py` (`record`, `list_for`) (AST-1/2)
- [x] 1.5 `api/routes/agent_sessions.py`: `GET /v1/agent-sessions?conversation_id=&limit=`, tenant/user scoped (AST-6)
- [x] 1.6 `api/routes/chat.py`: `_persist_agent_session` best-effort; `_run_tool` sets `started_at`, post-run row write, `_on_task_metrics` holder; accept `message_id`; tombstoned upsert→missing-conversation (AST-2/3/4, CD-2)
- [x] 1.7 `ports/browser.py`: `run_single` declares `on_task_metrics`; composio.py+mock.py accept+ignore (AST-5)
- [x] 1.8 `adapters/browser/composio_telemetry.py`: Logs API `session_id` + Usage API `event_count`, best-effort (ADR-7, AST-4)
- [x] 1.9 `db/conversation_repo.py`: delete→tombstone; filters exclude deleted; upsert→None tombstoned; `patch_conversation_title` (CD-1/2)
- [x] 1.10 `api/routes/conversations.py`: DELETE 404 missing/already-deleted; PATCH title-only (CD-1..3)
- [x] 1.11 `tests/test_agent_sessions.py` + `test_conversation_deletion.py`; extend `test_chat_stream.py` (FakeBrowser sig, row assert, ADR-7 mocked) (AST-1..6, CD-1..3)

## Phase 2: P1b — Frontend consume (PR 2)

- [x] 2.1 `frontend/app/(chat)/api/agent-sessions/route.ts` + `frontend/lib/backend/agent-sessions.ts` (AST-6)
- [x] 2.2 `frontend/hooks/use-agent-sessions.ts`; `agent-sessions/page.tsx`: Acciones column, `—` NULLs; i18n key (AST-3/6)
- [x] 2.3 `backend/ai/tools/agent-execution.ts`: `SUBTASK_TEMPLATES.consultaarca` → 7 labels (AST-3)
- [x] 2.4 `frontend/app/(chat)/api/messages/route.ts`: `activity` from persisted rows by `conversation_id` (AST-6)
- [x] 2.5 vitest: template length + type mapping; e2e reload case (AST-3/6)

## Phase 3: P2 — Deletion UX (PR 3)

- [x] 3.1 `frontend/app/(chat)/api/chat/route.ts`: DELETE 404→`{success:false,deleted:false}`; `saveConversation`→PATCH (CD-3)
- [x] 3.2 `frontend/lib/backend/conversations.ts`: `deleted:false` on 404; `patchConversationTitle` (CD-3)
- [x] 3.3 `frontend/components/chat/sidebar-history.tsx`: await DELETE; error toast; reconcile; invalidate; navigate active (CD-4)
- [x] 3.4 vitest + e2e delete/failure cases (CD-3/4)

## Phase 4: P3 — Landing light theme (PR 4)

- [x] 4.1 `frontend/app/layout.tsx`: remove ThemeProvider (keep scripts/Language/Clerk); `(chat)/layout.tsx`: scoped provider around SidebarShell (class attr, system default) (LLT-1/3)
- [x] 4.2 E2E: landing light on dark OS, chat toggle, no-flash (LLT-1/2/3)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1670 total: P1a ~950, P1b ~350, P2 ~250, P3 ~120 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1→P1a, PR 2→P1b, PR 3→P2, PR 4→P3 |

```text
Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High
```

### Suggested Work Units

| PR | Focused test command | Runtime harness | Rollback boundary |
|----|---------------------|-----------------|-------------------|
| 1 — telemetry+deletions | `uv run pytest` (unit + TestClient) | N/A: external creds; smoke per `SMOKE-INTEGRATIONS.md` | Revert PR 1; downgrade 0006 |
| 2 — frontend consume | `pnpm test:unit` + AST-6 e2e | `pnpm dev`: consultaarca chat → reload `/agent-sessions` | Revert PR 2 |
| 3 — deletion UX | `pnpm test:unit` + CD-4 e2e | `pnpm dev`: delete chat, reload, 2nd delete toast | Revert PR 3 (POST save) |
| 4 — theme scoping | `pnpm exec playwright test` | `pnpm dev`: emulate dark OS, toggle, no-flash | Revert PR 4 (root provider) |

P1a likely exceeds 400 lines → apply micro-splits. Chain strategy undecided → orchestrator asks before apply.