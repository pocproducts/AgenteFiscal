# Proposal: Browser Tools Streaming Generalization

## Intent

`sistemaregistral` is the only tax tool wired to the embedded browser session + SSE task-streaming monitor. Backend dispatch and the BFF gate are hardcoded to it; UI and SSE pipeline are already generic. Generalize the mechanism to every browser-based tool, reusing each tool's existing task/template/parser with declarative wiring only.

## Scope

### In Scope — Phase 1 (low risk)
- Wire `deudavencimientos`, `misfacilidades`, `rentascordoba` (+ keep `sistemaregistral`) through: intent router → declarative dispatch → per-tool formatter → parametrized BFF gate.
- Declarative `ToolSpec` map (`tool_key → keywords, task flags, formatter, window_ms`) shared by stream / no-stream / wizard endpoints.
- BFF: replace `isRegistroRegistralCommand` with a tool-key matcher; parametrize toolName/toolKey/windowMs in `data-agent-session-start`.
- Align `AGENT_SESSION_WINDOW_MS` (10 min) with task timeouts (FacilidadesTask 900s): per-tool window `= timeout + margin`.

### Out of Scope
- `enviarmail` — SMTP/Resend, no browser, no monitor (explicit). `informefiscal` — aggregator; a multi-tool trigger is a separate change. UI (`agent-sidebar.tsx`, `data-stream-handler.tsx`) — already generic, zero changes.

### Phase 2 — decision needed
- `consultaarca`, `calendariovencimientosarca` lack task/templates. Options: (a) new ComposioBrowser NL templates; (b) deterministic — ARCA padrón via TAXPAYER_QUERY, calendar via engine `POST /v1/calendar`. **Recommended (b):** zero Composio sessions, engines tested; (a) only if live visualization is required.

## Capabilities

### New Capabilities
- `browser-tool-streaming`: generalized embedded-browser session + SSE task monitor for all browser tax tools (ToolSpec dispatch, per-tool events, window alignment).

### Modified Capabilities
- None — `openspec/specs/` is empty; this is the first spec.

## Approach

1. Backend: add intents to `Intent`/`detect()` with priority over TAXPAYER_QUERY; `ToolSpec` registry; refactor the SISTEMA_REGISTRAL SSE branch (`chat.py` L846-993) into ToolSpec-driven dispatch, reusing queue/callbacks/generator; standalone formatters per tool.
2. BFF: regex matcher `\b(?:deudavencimientos|misfacilidades|rentascordoba|sistemaregistral|consultaarca|calendariovencimientosarca)\b`; pass toolName/toolKey/windowMs; use the tool window for the remaining-window wait.
3. Keep TS mocks `ejecutar*` (`backend/ai/tools/fiscal-tools.ts`) as fallback for tools without backend; Phase-1 uses the stream.

## Affected Areas

| Area | Impact |
|------|--------|
| `backend/agente_fiscal/domain/intent_router.py` | Modified — new intents + priority |
| `backend/agente_fiscal/api/routes/chat.py` | Modified — ToolSpec dispatch |
| `backend/agente_fiscal/adapters/browser/workflows/*.py` | Modified — per-tool formatters |
| `backend/agente_fiscal/adapters/browser/task.py` | Modified — window alignment |
| `frontend/app/(chat)/api/chat/route.ts` | Modified — matcher + params |
| `frontend/lib/agent-window.ts` | Modified — per-tool window |
| `backend/ai/tools/fiscal-tools.ts` | Modified — fallback only |
| `frontend/components/chat/*` | Unchanged — already generic |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Composio session cost × tools | High | Window keeps session alive; deterministic paths |
| Window vs 900s task timeout closes UI early | High | Per-tool window ≥ timeout + margin |
| Intent collisions with TAXPAYER_QUERY/REPORTE_COMPLETO | Med | Keyword priority + specific phrases |
| Phase-2 template quality | Med | Deterministic engines (option b) |
| TS-mock divergence | Low | Documented fallback |

## Rollback Plan

Revert one PR: restore `isRegistroRegistralCommand` gate and hardcoded SISTEMA_REGISTRAL branch, drop new intents. No migrations, no persisted data, UI untouched.

## Dependencies

- Composio (in use); `/v1/calendar` engine (exists). None new.

## Success Criteria

- [ ] Direct commands for the 3 Phase-1 tools emit the 5 SSE events with per-tool data (SSRR parity).
- [ ] sistemaregistral shows zero regression.
- [ ] Facilidades window covers full 900s runtime.
- [ ] Option-b tools emit `complete` + data with no browser session.
- [ ] `frontend/components/chat/*` unchanged.