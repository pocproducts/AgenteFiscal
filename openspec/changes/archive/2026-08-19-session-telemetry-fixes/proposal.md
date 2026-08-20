# Proposal: Session Telemetry Fixes

## Intent

Agent sessions have no real telemetry: engines emit no session events, browser telemetry is ephemeral client SWR, `hydrate` never runs. Make it persisted, backend-owned, correct per tool — id, "Acciones", profile, start, duration, cost, state — surviving reloads, DB aligned (user requirement). Also bundles: delete-reappears, dark landing.

## Split Recommendation

Not one coherent intent — recommend 3 proposals: P1 telemetry, P2 deletion, P3 theme (capability names below; orchestrator decides).

## Scope

### In Scope

- **P1** — New `agent_sessions` table (tool, message_id, profile_id?, status, tasks JSONB, cost_cents, started/completed, tenant, user) + migration aligned with existing heads. Backend writes one row per tool run (engine + browser), no callbacks. `consultaarca`: empty session/profile ids, "Acciones" header + 7 defaults, "Comenzó" = action time, "Duración" = round-trip, cost 0. Browser: session id from provider, profile from user-created, states persisted. Fix `on_task_metrics` TypeError (guard or post-run persist). `GET /v1/agent-sessions` + BFF; page + hydrate use it.
- **P2** — no-recreate title-patch; upsert never resurrects; honest 404 `deleted:false`; awaited client delete + toast + invalidation.
- **P3** — ThemeProvider scoped to `(chat)`; landing always light; no flash regression.

### Out of Scope

Historical sessions; `browser_sessions` unify (coexist = design decision); non-zero cost; engine live URLs; `/embed/*`; extra ownership.

## Capabilities

### New Capabilities
- `agent-session-telemetry`: persisted sessions for engine + browser (table, post-run write, API/BFF, "Acciones", hydrate).
- `conversation-deletion`: delete that sticks (no-recreate, honest 404, client errors, invalidation).
- `landing-light-theme`: landing always light; provider scoped to chat.

### Modified Capabilities
- None — `openspec/specs/` empty.

## Approach

Exploration A1 + B1+2 + C1: `agent_sessions` as single telemetry source, post-tool backend writes (no callbacks → TypeError gone); no-recreate delete + honest 404; provider scoped to `(chat)`. Coordinate with in-flight `browser-tools-streaming` (chat.py overlap).

## Affected Areas

| Area | Impact |
|---|---|
| `backend/agente_fiscal/api/routes/chat.py` | Modified — persist, TypeError guard, no-resurrect |
| `backend/agente_fiscal/db/`, Alembic, `conversations.py` | Modified — migration, no-recreate, honest 404 |
| `backend/agente_fiscal/adapters/browser/` | Modified — callback contract |
| `frontend/app/(chat)/api/*` (chat, agent-sessions) | Modified/New — delete, title, BFF proxy |
| `frontend` hooks, sidebar, agent-sessions page, i18n | Modified — fetch, hydrate, delete, "Acciones" |
| `frontend/app/layout.tsx`, `(landing)/layout.tsx` | Modified — theme scoping |

## Risks

| Risk | Likelihood |
|---|---|
| TypeError with composio default | High — broken today |
| Migration vs existing schema | Med — review, reversible |
| No-create title breaks new-chat | Med — confirm timing |
| Theme scoping flash/toggle | Med — visual check |
| In-flight chat.py conflict | Med — task ordering |

## Rollback Plan

- **P1**: revert one PR; drop table via new reversible revision.
- **P2**: restore upsert + 404 swallow (accepted trade).
- **P3**: restore root ThemeProvider.

## Dependencies

Alembic ordering; in-flight `browser-tools-streaming`; composio config for real verify.

## Success Criteria

- [ ] `consultaarca` rows: 7 "Acciones", empty ids, round-trip duration, cost 0; persist across reload.
- [ ] Browser stream: no TypeError; session/profile from contract; states persisted.
- [ ] Deleted conversation stays deleted; 404 → `deleted:false`; client toasts errors.
- [ ] Landing light on dark OS; chat toggle works; migration head valid.