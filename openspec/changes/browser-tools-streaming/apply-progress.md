# Apply Progress: Browser Tools Streaming Generalization

Change: `browser-tools-streaming`
Status: implementation complete (all 18 tasks) — pending verify phase
Baseline commit: `13a13bf` (WIP previo commit como base limpia)
Delivery strategy: single-pr, 3 work units (sin PRs — solo commits por work unit)

## Work Units Committed

| Unit | Scope | Commit | Files | Result |
|---|---|---|---|---|
| 1 | ToolSpec registry + intent routing | `ae9d882` | `domain/tool_spec.py`, `domain/intent_router.py`, `tests/test_tool_spec.py`, `tests/test_intent_router.py`, `api/routes/chat.py` (_ACTION_NAMES) | ✅ |
| 2 | Formatters markdown por tool | `c0cf9a3` | `domain/response_builder.py`, `tests/test_response_builder.py` | ✅ |
| 3 | Dispatch refactor stream/no-stream por ToolSpec | `d923252` | `api/routes/chat.py` | ✅ |
| 4 | BFF matcher paramétrico + window map | `425d90f` | `frontend/lib/agent-window.ts`, `frontend/lib/agent-window.test.ts`, `frontend/app/(chat)/api/chat/route.ts` | ✅ |
| 5 | Contrato SSE test_chat_stream + 2 bugs del dispatch | commit tras 425d90f | `api/routes/chat.py`, `tests/test_chat_stream.py` | ✅ |

Committs creados con identidad del repo (`-c user.name/-c user.email`); repo sin git config global.

## Bugs encontrados y fixeados durante apply (importante para verify)

1. **Serialización SSE de date/Decimal anidados** — `_run_browser_tool` devolvía
   `out.model_dump()` (sin `mode='json'`); las tools con campos `date`/`Decimal`
   anidados (deudavencimientos, misfacilidades, rentascordoba) rompían el framing
   SSE con `TypeError: Object of type date is not JSON serializable`. Fix:
   `out.model_dump(mode='json')` (chat.py, igual que `_run_engine_tool`).
2. **Race progress/complete en el stream** — `_run_tool` ponía `complete` directo
   (`await queue.put`) mientras `progress`/`live_url`/`agent_step` van por
   `call_soon_threadsafe` (programados). Tras un engine rápido, `complete` ganaba
   la race y cortaba el stream antes de drenar el `progress` encolado — flaky
   (3/5 fallos en test de contrato). Fix: `complete` también por
   `_loop.call_soon_threadsafe(queue.put_nowait, ...)` → mismo FIFO. Estable 9/9
   en 6 corridas consecutivas.

## Verification Summary (pre-verify)

- `pytest` focal (5 archivos): **125 passed**; full suite: 147 passed, 1 failed
  pre-existente (`test_features.py::test_feature_flags_default_values`,
  sensible a .env — verificado igual en baseline `13a13bf`), 137 errors de
  fixtures por servicios externos caídos (Redis en 6379 / DB) — **pre-existentes
  en baseline**, no relacionados (baseline worktree: 14/14 errors en el mismo
  archivo de fixture).
- Frontend: `typecheck` limpio; `vitest` agent-window.test.ts 10 tests PASS;
  ultracite check: los 17 reportes restantes son 100% archivos pre-existentes
  (profiles/actions), ninguno en archivos tocados.
- 6.3: `fiscal-tools.ts` 0 commits en el rango → mocks conservados (design OK).
- 6.4: `frontend/components/chat/*` 0 commits en el rango → UI intacta (design OK).
- 6.2 smoke manual con credenciales reales:
  - `consultaarca CUIT 30716395541` → live TA ARCA + padrón real (GRUPPO
    MURATORE S.A.S.) + 5-event framing: conversation_start → progress → complete. ✅
  - `calendariovencimientosarca CUIT 30716395541` → live TA + calendario real
    (Ret./Perc. SICORE — 8/2026, Ganancias...) con 2 progress. ✅
  - Browser (`deudavencimientos`): Composio responde 403 a nivel workspace
    ("Execution of toolkit 'BROWSER_TOOL' is temporarily disabled by the
    administrator", code 10403) — **bloqueo externo documentado en memoria #169**,
    no es código. El dispatch no falla: captura como `BROWSER_ERROR` y el stream
    emite `complete.data.error` + reply limpio "Error de conexión" sin traceback.
    El contrato de failure queda verificado end-to-end con credenciales reales.

## Diff budget

`git diff 13a13bf..HEAD --numstat`: 1490 added + 61 deleted (11 archivos).
El forecast de tasks.md decía 650–750; el delta real incluye los tests de
contrato (test_chat_stream ~390 líneas) y los 5 archivos de test/registro.
Si el review budget de 800 líneas se aplica al diff total, reportar al
orchestrator (los work units quedan separables por commit si se necesita
chained PR retroactivo).

## Fase 6 no cubierta por apply (verify scope)

- E2E de browser completo con sesión Composio viva (live_url/agent_step reales)
  queda pendiente del desbloqueo del toolkit en el workspace Composio.
- `apply-progress` merge: primer archivo creado (no había previo).