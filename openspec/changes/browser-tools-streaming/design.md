# Design: Browser Tools Streaming Generalization

## Technical Approach

Declarative `ToolSpec` registry (backend `domain/`) drives intent routing, SSE dispatch, and formatters for the six browser tools; the BFF gate becomes a tool-key matcher parametrizing session-start from a frontend window map; Phase-2 tools run deterministic engines without Composio. Maps to proposal approach 1–3 and all `browser-tool-streaming` requirements.

## Architecture Decisions

### D1 — Phase 2: deterministic (option b) — CLOSED

| Option | Tradeoff | Decision |
|---|---|---|
| (a) ComposioBrowser NL templates | Live visualization; template cost/quality risk; +1 cloud session/tool | Rejected — spec recommends (b) |
| (b) padrón A5 (`arca_ws.consultar_cuit`) + `RulesEngine.calcular` (reuse `POST /v1/calendar`) | No live browser, data-only | **Chosen** — zero Composio cost; engines tested in production |

(b) emits `conversation_start → progress* → complete`, omitting `live_url`/`agent_step` (spec "No session, no live_url"). `complete.data` = engine output; errors reuse `routes/calendar.py` codes: `TA_UNAVAILABLE | TAXPAYER_QUERY_FAILED | TAXPAYER_NOT_FOUND | CALENDAR_FAILED`.

### D2 — ToolSpec location/shape

Domain: `backend/agente_fiscal/domain/tool_spec.py` (follows `intent_router.py` precedent; adapters stay task-only). Fields: `tool_key, intent, keywords, task_flags, formatter_name, needs_browser, tool_name`.

### D3 — Window single source of truth: frontend

| Option | Tradeoff | Decision |
|---|---|---|
| Backend `window_ms` → BFF via session-start | Needs pre-flight; session-start is optimistic (route.ts opens BEFORE the backend call, L305–322) | Rejected |
| Frontend map | Synchronous; UI clock already derives from the event value | **Chosen** — `agent-window.ts` keeps `AGENT_SESSION_WINDOW_MS` default + `TOOL_WINDOW_OVERRIDES` (= timeout + 60s) |

`task.py`/`factory.py` need NO changes; proposal's "task.py window alignment" resolves here.

## ToolSpec Registry

| tool_key | intent | task_flags / engine | formatter | browser | window override |
|---|---|---|---|---|---|
| sistemaregistral | SISTEMA_REGISTRAL | `with_registro=True` | `format_registro_response` | yes | 660_000 (11m ≥ 600s) |
| deudavencimientos | DEUDA_VENCIMIENTOS | `with_deuda=True` | `format_deuda_response` | yes | 660_000 |
| misfacilidades | MIS_FACILIDADES | `with_facilidades=True` | `format_facilidades_response` | yes | 960_000 (16m ≥ 900s) |
| rentascordoba | RENTAS_CORDOBA | `with_iibb=True, provincia='CORDOBA'` | `format_rentas_response` | yes | 660_000 |
| consultaarca | CONSULTA_ARCA | padrón A5 | `format_consultaarca_response` | no | 120_000 |
| calendariovencimientosarca | CALENDARIO_VENCIMIENTOS_ARCA | `RulesEngine.calcular` | `format_calendario_response` | no | 120_000 |

## Data Flow

    detect ──> Intent ──> INTENT_TO_KEY ──> ToolSpec
       queue + _progress/_on_live_url/_on_step (existing framing)
    browser: build_browser_tasks(**flags) ─> run_single ─> DeudaOutput
    engine:  consultar_cuit / engine.calcular ─> dict
       formatter ─> complete{reply,data} ─SSE─> BFF ─> data-agent-* events

## Intent Router (`domain/intent_router.py`)

New enums `DEUDA_VENCIMIENTOS, MIS_FACILIDADES, RENTAS_CORDOBA, CONSULTA_ARCA, CALENDARIO_VENCIMIENTOS_ARCA`. Check order (all before REPORTE_COMPLETO → TAXPAYER_QUERY → UNKNOWN, per spec): sistemaregistral → deudavencimientos → calendariovencimientosarca → misfacilidades → rentascordoba → consultaarca.

Keywords (substring on lowercased msg, existing pattern): deuda `deudavencimientos|deuda y vencimientos|deuda`; calendario `calendariovencimientosarca|calendario|vencimientos`; facilidades `misfacilidades|mis facilidades|plan de pago|plan de pagos`; rentas `rentascordoba|rentas cordoba|iibb|ingresos brutos`; consulta `consultaarca|obligaciones`. Deuda checked before calendario so "deuda y vencimientos" wins; "vencimientos" alone → calendario. `REPORTE_COMPLETO` stays the aggregator — matched only when no tool keyword hit; mixed "reporte + tool" → tool (spec scenario). `_ACTION_NAMES` extended.

## Dispatch (`api/routes/chat.py`)

Replace branch L923–993 with generic `_generate_tool` reusing the queue/callback/generator framing; `spec = TOOL_SPECS[INTENT_TO_KEY[intent]]`. Browser: `_run_browser_tool(spec, cuit, _progress, _on_live_url, _on_step)` (generalized `_handle_sistemaregistral`: build tasks → `run_single` → formatter → `complete`). Engine: `_run_engine_tool(spec, cuit, _progress)` (one `progress` per stage, no browser callbacks). Non-stream reuses both via `_handle_tool_data(spec, cuit, echo_func)`; wizard keeps its flags but takes identity/formatter from ToolSpec.

## BFF (`app/(chat)/api/chat/route.ts`)

Replace `isRegistroRegistralCommand` with the spec regex `/\b(?:deudavencimientos|misfacilidades|rentascordoba|sistemaregistral|consultaarca|calendariovencimientosarca)\b/i`. `toolKey` from match; `toolName` from `TOOL_NAMES[toolKey]` (PascalCase e.g. `MisFacilidades`); `windowMs = TOOL_WINDOW_OVERRIDES[toolKey] ?? AGENT_SESSION_WINDOW_MS` in session-start and the remaining-window wait (L468–476). Error path unchanged (`data.error` → `{status:"error"}`).

## Formatters (`domain/response_builder.py`)

Per-tool `format_<tool>_response(data: dict|None, cuit: str) -> str` (over a generic section formatter — zero risk to existing, mirrors style). Error-first branch (BROWSER_ERROR → short "Motivo"), then markdown over existing `DeudaOutput` keys: deuda → `deuda_actual`/`vencimientos`/`deudas`; facilidades → `facilidades`; rentas → `registro.iibb_jurisdicciones`/`iibb_cuotas_vencidas`; padron → `obligaciones`; calendario → `vencimientos`/`observaciones`.

## Mocks (`backend/ai/tools/fiscal-tools.ts`)

Unchanged. `ejecutar*` stay for LLM tool-calls of backend-less tools (consultaarca, calendario, informefiscal, enviarmail). Phase-1 tools NEVER silently fall back — BFF always streams; unreachable backend surfaces `describeBackendError`.

## Errors

`complete.data = {error, detail}` (existing shape). Browser: `COMPOSIO_KEY_MISSING | INTEGRATION_DISABLED | BROWSER_ERROR` (kept). Engine: D1 codes. BFF closes `{status:"error"}` — existing, zero UI change.

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/agente_fiscal/domain/tool_spec.py` | Create | ToolSpec + TOOL_SPECS + INTENT_TO_KEY |
| `backend/agente_fiscal/domain/intent_router.py` | Modify | 5 intents, keywords, priority |
| `backend/agente_fiscal/domain/response_builder.py` | Modify | 5 formatters |
| `backend/agente_fiscal/api/routes/chat.py` | Modify | Generic dispatch + `_ACTION_NAMES` |
| `frontend/app/(chat)/api/chat/route.ts` | Modify | Matcher + parametrization |
| `frontend/lib/agent-window.ts` | Modify | TOOL_WINDOW_OVERRIDES |
| `backend/agente_fiscal/tests/test_tool_spec.py` | Create | Registry/priority tests |

## Interfaces / Contracts

```python
@dataclass(frozen=True)
class ToolSpec:
    tool_key: str              # 'misfacilidades'
    intent: Intent             # Intent.MIS_FACILIDADES
    keywords: tuple[str, ...]  # intent-router keywords
    task_flags: dict[str, Any] # build_browser_tasks(**flags); {} for engines
    formatter_name: str        # 'format_facilidades_response'
    needs_browser: bool
    tool_name: str             # 'MisFacilidades' (BFF display)
```

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit (pytest, beside existing backend tests) | `detect()` priority; TOOL_SPECS completeness/keyword disjointness; window map ≥ timeouts | Direct assertions |
| Integration | 5-event contract per Phase-1 tool; no `live_url` for engines; error shapes | FastAPI TestClient on the stream |
| E2E (Playwright) | BFF parametrization + error close | Drive route, assert session events |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary; matcher change is HTTP app logic.

## Migration / Rollout

No migration, no persisted data. Phase-1 wiring with SSRR parity as regression gate, then Phase-2 engines via the same dispatch. Rollback per proposal: revert one PR.

## Open Questions

None blocking. `informefiscal`/`enviarmail` excluded per spec.