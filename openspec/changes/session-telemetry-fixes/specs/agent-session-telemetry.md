# Agent Session Telemetry Specification

## Purpose

Backend-owned, persisted telemetry for agent tool runs (engine + browser), replacing ephemeral client-side SWR state. The backend writes ONE row per tool run into `agent_sessions`, exposed via API + BFF, consumed by the agent-sessions page and chat hydrate.

## Requirements

### Requirement: AST-1 — `agent_sessions` persistence table

The system MUST create an `agent_sessions` table via a reversible Alembic migration with columns: `tool`, `message_id`, `profile_id`, `status`, `tasks` (JSONB), `cost_cents`, `started_at`, `completed_at`, `tenant`, `user`. The migration MUST chain from the current Alembic head without conflicting with existing revisions, and all columns MUST be nullable or defaulted so existing flows never break writes.

#### Scenario: Migration applies cleanly on existing schema

- GIVEN a database at the current Alembic head
- WHEN the new revision is applied
- THEN the table exists with every required column
- AND `alembic downgrade` reverses it cleanly

#### Scenario: Engine row tolerates NULL profile

- GIVEN an engine tool run with no profile bound
- WHEN the backend persists the session row
- THEN the insert succeeds with `profile_id` NULL
- AND no constraint rejects the row

### Requirement: AST-2 — One row per tool run, persisted post-execution

The backend MUST persist exactly one `agent_sessions` row per tool run (engine and browser) immediately after execution completes. Persistence MUST NOT depend on provider callbacks; the backend MUST write the row itself after `run_single`/engine dispatch returns.

#### Scenario: Engine run persists a row

- GIVEN a completed `consultaarca` engine tool run
- WHEN the backend finishes execution
- THEN one `agent_sessions` row is written for that `message_id`

#### Scenario: Browser run persists without callbacks

- GIVEN a completed browser tool run on browserbase, composio, or mock
- WHEN execution returns
- THEN one `agent_sessions` row is written
- AND no telemetry depends on `on_task_metrics`

### Requirement: AST-3 — `consultaarca` row shape ("Acciones")

For engine tool runs, the persisted row MUST carry: empty session id, NULL/empty profile id, "Acciones" as the first column header populated with the 7 default tasks, "Comenzó" set to the request start time, "Duración" equal to the request round-trip time, and `cost_cents` = 0. Status/state transitions MUST be persisted.

#### Scenario: Consultaarca row complete

- GIVEN a finished `consultaarca` run
- WHEN the agent-sessions page reads the persisted row
- THEN session id and profile id are empty and "Acciones" shows the 7 defaults
- AND "Comenzó"/"Duración" match start time/round-trip and cost is 0

#### Scenario: Row survives reload

- GIVEN a persisted `consultaarca` row
- WHEN the user reloads the agent-sessions page
- THEN the row is still present with all fields intact

### Requirement: AST-4 — Browser row shape from provider contract

For browser tool runs, the row MUST set the session id from the provider API response, the profile id from the user-created profile, start time and duration from execution, `cost_cents` = 0, and MUST persist status/state transitions.

#### Scenario: Browser session uses provider id

- GIVEN a browser run with a provider session id and user-created profile
- WHEN the row is persisted
- THEN session id equals the provider value and profile id equals the profile's id

### Requirement: AST-5 — `on_task_metrics` TypeError eliminated

The backend MUST NOT pass `on_task_metrics` to a provider that does not support it — by gating the callback on provider capability or by persisting metrics post-run. The browser runner port contract MUST match every provider implementation. The dispatch MUST NOT raise `TypeError: unexpected keyword argument 'on_task_metrics'` for composio or mock.

#### Scenario: Composio dispatch succeeds

- GIVEN `BROWSER_PROVIDER=composio` and a stream browser tool call
- WHEN the dispatch calls `run_single`
- THEN no TypeError is raised
- AND metrics are still persisted post-run

#### Scenario: Mock dispatch succeeds

- GIVEN MockBrowser configured
- WHEN `run_single` executes
- THEN the call succeeds without an unknown-argument error

### Requirement: AST-6 — API, BFF, page, and hydrate consume persisted data

The system MUST expose `GET /v1/agent-sessions` returning persisted rows and a BFF proxy that the agent-sessions page consumes. Chat hydrate MUST consume real persisted activity instead of the hardcoded empty array.

#### Scenario: API returns persisted rows

- GIVEN persisted `agent_sessions` rows for the tenant/user
- WHEN `GET /v1/agent-sessions` is called
- THEN the response contains those rows

#### Scenario: Hydrate uses real data

- GIVEN a conversation with persisted agent activity
- WHEN the chat loads
- THEN `hydrate` runs with real data rather than `activity: []`