# browser-tool-streaming Specification

## Purpose

Generalize the embedded live-browser session + SSE task-streaming monitor (currently sistemaregistral-only) to all browser tax tools via declarative ToolSpec dispatch. First spec for this capability. `enviarmail` (SMTP) and `informefiscal` (aggregator) are excluded.

## Requirements

### Requirement: Direct Command Agent Session

For any Phase-1 tool (`deudavencimientos`, `misfacilidades`, `rentascordoba`, `sistemaregistral`) triggered by direct command, the system MUST open an agent session with that tool's `toolName`, `toolKey`, and `windowMs`.

#### Scenario: Direct deuda command opens full flow

- GIVEN the command "deudavencimientos CUIT 20-12345678-9"
- WHEN intent detection and the BFF matcher resolve the tool
- THEN the BFF emits `data-agent-session-start` for `deudavencimientos`
- AND the monitor shows the live browser with tasks streaming

### Requirement: Declarative ToolSpec Dispatch

The backend MUST dispatch browser tools via a `ToolSpec` map (`tool_key` to keywords, task flags, formatter, `window_ms`) shared by stream, no-stream, and wizard endpoints, replacing the hardcoded SISTEMA_REGISTRAL branch.

#### Scenario: Endpoints resolve the same spec

- GIVEN a ToolSpec registered for `misfacilidades`
- WHEN any endpoint dispatches the tool
- THEN all resolve the same spec, flags, and formatter

### Requirement: Intent Router Priority

The intent router MUST add browser-tool intents ranked above `TAXPAYER_QUERY` and `REPORTE_COMPLETO`.

#### Scenario: Keyword collision resolved by priority

- GIVEN a message mixing tool keyword "deudavencimientos" with generic "deuda"
- WHEN `detect(context)` runs
- THEN the router returns the browser-tool intent, not TAXPAYER_QUERY

### Requirement: BFF Tool-Key Matcher

The BFF MUST match the six tool keys by regex (`deudavencimientos|misfacilidades|rentascordoba|sistemaregistral|consultaarca|calendariovencimientosarca`), replacing the `isRegistroRegistralCommand` gate, and MUST parametrize session start and the remaining-window wait from the ToolSpec.

#### Scenario: Matcher parametrizes session start

- GIVEN a matching direct command
- WHEN the BFF prepares `data-agent-session-start`
- THEN toolName, toolKey, windowMs come from the ToolSpec
- AND the wait uses that tool's window

### Requirement: SSE Event Contract

The backend MUST emit `conversation_start`, `progress`, `live_url`, `agent_step`, `complete` for every Phase-1 tool with per-tool data. `live_url` MUST fire only when a Composio session exists.

#### Scenario: Five events for rentascordoba

- GIVEN a streamed run for `rentascordoba`
- WHEN tasks execute
- THEN events arrive in contract order and `complete` carries that tool's output

#### Scenario: No session, no live_url

- GIVEN a run with no Composio session
- WHEN events are emitted
- THEN `live_url` is absent and the remaining events still follow the contract

### Requirement: Window Alignment

Per-tool `window_ms` MUST be >= the tool's task timeout plus margin, so the UI never closes before the backend finishes.

#### Scenario: Facilidades covers its 900s timeout

- GIVEN `FacilidadesTask` timeout of 900s
- WHEN the BFF sets the window for `misfacilidades`
- THEN window_ms >= 900s + margin and the session stays open for the whole run

### Requirement: Backend Error Closes Session in Error State

On failure the system MUST emit `complete` with `data.error`, and the BFF MUST close the session with error status.

#### Scenario: Task failure propagates to the UI

- GIVEN a Composio task fails mid-run
- WHEN the run finishes with an error
- THEN `complete` carries data.error
- AND the BFF closes the session with status "error"

### Requirement: Scope Exclusions

`enviarmail` MUST NOT open a monitor or agent session (SMTP unchanged); `informefiscal` MUST NOT trigger the browser mechanism.

#### Scenario: enviarmail stays on its SMTP path

- GIVEN the command "enviarmail" with a recipient
- WHEN the BFF evaluates the matcher
- THEN no session or monitor opens and the SMTP flow proceeds as before

### Requirement: sistemaregistral Zero Regression

`sistemaregistral` MUST keep current behavior at contract level: same session flow, events, output data.

#### Scenario: SSRR parity through generalized dispatch

- GIVEN a sistemaregistral command
- WHEN the ToolSpec dispatch handles it
- THEN events and output match the previous hardcoded path

### Requirement: Phase 2 Alternative Scenarios

Design MUST choose between (a) new ComposioBrowser NL templates and (b) deterministic engines (ARCA padron via TAXPAYER_QUERY; calendar via `POST /v1/calendar`); (b) is recommended. The decision MUST be closed in design.

#### Scenario: Option (b) calendar without browser

- GIVEN design selects option (b) for `calendariovencimientosarca`
- WHEN the tool runs
- THEN no browser session or `live_url` is created
- AND `complete` carries the engine's calendar data

#### Scenario: Option (a) template with browser monitor

- GIVEN design selects option (a) for `consultaarca`
- WHEN the new template runs
- THEN the full browser-monitor flow applies via that tool's ToolSpec

### Requirement: TS Mock Fallback

TS `ejecutar*` mocks MUST remain a documented fallback for tools without a real backend; Phase-1 tools MUST stream when their backend exists.

#### Scenario: Mock fallback for a backend-less tool

- GIVEN a tool without a real backend
- WHEN invoked
- THEN the mock path returns that tool's data and Phase-1 tools still stream