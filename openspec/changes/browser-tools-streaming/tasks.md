# Tasks: Browser Tools Streaming Generalization

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 650–750 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR, 3 units |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Work Units

| Unit | Goal | PR | Focused test cmd | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | ToolSpec + intents | PR 1 | `pytest tests/test_tool_spec.py test_intent_router.py` (backend/) | N/A — pure domain | revert `domain/tool_spec.py` + `domain/intent_router.py` |
| 2 | Formatters + dispatch | PR 1 | `pytest agente_fiscal/tests/test_chat_stream.py` | N/A in CI (real creds); manual 6.2 | revert `response_builder.py` + `chat.py` |
| 3 | BFF + window map | PR 1 | `pnpm test:unit` | `pnpm dev`, direct cmd → SSE events (real creds) | revert `chat/route.ts` + `agent-window.ts` |

## Phase 1: Foundation — ToolSpec registry

- [x] 1.1 Create `backend/agente_fiscal/domain/tool_spec.py`: frozen `ToolSpec` dataclass (tool_key, intent, keywords, task_flags, formatter_name, needs_browser, tool_name) + `TOOL_SPECS` (6 registry rows) + `INTENT_TO_KEY`.
- [x] 1.2 Create `backend/agente_fiscal/tests/test_tool_spec.py`: 6 tools registered; keyword sets disjoint; `INTENT_TO_KEY`↔`TOOL_SPECS` complete; formatters resolvable.

## Phase 2: Intent routing

- [x] 2.1 `domain/intent_router.py`: add 5 `Intent` members + keyword checks BEFORE REPORTE_COMPLETO/TAXPAYER_QUERY, priority sistemaregistral→deudavencimientos→calendariovencimientosarca→misfacilidades→rentascordoba→consultaarca.
- [x] 2.2 `api/routes/chat.py` L1111: extend `_ACTION_NAMES` with the 5 new intents.
- [x] 2.3 Create `tests/test_intent_router.py`: "deuda y vencimientos"→DEUDA_VENCIMIENTOS; "vencimientos"→CALENDARIO_VENCIMIENTOS_ARCA; tool keyword beats REPORTE_COMPLETO; plain "consulta"→TAXPAYER_QUERY.

## Phase 3: Formatters

- [x] 3.1 `domain/response_builder.py`: add format_deuda_response, format_facilidades_response, format_rentas_response, format_consultaarca_response, format_calendario_response — error-first branch, markdown over DeudaOutput keys per design.
- [x] 3.2 Unit tests: error-first + section rendering per formatter.

## Phase 4: Dispatch refactor (`api/routes/chat.py`)

- [x] 4.1 Generalize `_handle_sistemaregistral` L343 → `_run_browser_tool(spec, cuit, callbacks)`: `build_browser_tasks(**spec.task_flags)` → `ComposioBrowser.run_single` → formatter by spec; keep COMPOSIO_KEY_MISSING/INTEGRATION_DISABLED/BROWSER_ERROR guards.
- [x] 4.2 Add `_run_engine_tool(spec, cuit, _progress)`: consultaarca→`arca_ws.consultar_cuit`; calendario→`RulesEngine.calcular` (reuse calendar.py error codes); `progress` per stage, no browser callbacks.
- [x] 4.3 Replace stream branch L923–993 with generic `_generate_tool` (`TOOL_SPECS[INTENT_TO_KEY[intent]]`) reusing queue/callbacks/generator; `conversation_start→progress*→complete`; live_url/agent_step only with session.
- [x] 4.4 Non-stream L1225 + wizard → `_handle_tool_data(spec, cuit, echo_func)` from ToolSpec.

## Phase 5: BFF + window map (frontend)

- [x] 5.1 `frontend/lib/agent-window.ts`: export `TOOL_KEY_RE`; add `TOOL_NAMES` (PascalCase) + `TOOL_WINDOW_OVERRIDES` (misfacilidades 960_000; engines 120_000; others 660_000), fallback `AGENT_SESSION_WINDOW_MS`.
- [x] 5.2 `frontend/app/(chat)/api/chat/route.ts`: replace `isRegistroRegistralCommand` with `TOOL_KEY_RE`; parametrize toolName/toolKey/windowMs (session-start L310, wait L468); error keeps `{status:"error"}`.
- [x] 5.3 Create `frontend/lib/agent-window.test.ts` (vitest): matcher hits all 6 keys, rejects enviarmail/informefiscal; overrides ≥ timeouts (facilidades 900s).

## Phase 6: Integration, E2E, docs

- [x] 6.1 Create `tests/test_chat_stream.py` (TestClient, mock ComposioBrowser): 5-event contract per Phase-1 tool; SSRR parity for sistemaregistral; engines emit no live_url/agent_step; failure → `complete.data.error` + BFF `{status:"error"}`.
- [x] 6.2 Manual smoke: full stack dev, commands show monitor + 5 events; enviarmail none (real creds).
- [x] 6.3 `fiscal-tools.ts`: keep `ejecutar*` documented fallback; Phase-1 never falls back silently.
- [x] 6.4 Verify `frontend/components/chat/*` untouched (`git diff --stat`).