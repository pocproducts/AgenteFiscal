# Exploration extra — session-telemetry-fixes (evidencia detallada)

Evidencia file:line que soporta exploration.md. Solo lectura; ningún archivo de código fue modificado.

## 1. Cadena completa de borrado de conversación

```
sidebar-history.tsx:136-148            handleDelete: mutate optimista (saca la fila) +
                                       fetch(`${BASE}/api/chat?id=${id}`, {method:"DELETE"})
                                       → fire-and-forget, SIN await ni catch (rejection silenciosa)
api/chat/route.ts:608-638              DELETE handler: deleteConversation(chatId)
                                       → 404 del backend = response 200 {success:true} (no-op)
lib/backend/conversations.ts:77-82     deleteConversation → DELETE /v1/conversations/{id}
conversations.py:225-250               delete endpoint → repo_delete_conversation
conversation_repo.py:250-272           SELECT ... tenant_id + user_id(role member) → session.delete → commit
                                       → False ⇒ 404 CONVERSATION_NOT_FOUND
```

### Re-materialización (por qué "vuelve a aparecer")

1. **`upsert_conversation` crea si no existe** — conversation_repo.py:84-93 (`if conv is None: conv = Conversation(...); session.add(conv)`).
   - Caller stream: `chat.py:304` — cada turno persiste; si el chat borrado sigue abierto en el cliente, el próximo mensaje recrea la fila.
   - Caller título: `frontend/app/(chat)/api/chat/route.ts:586-589` — `saveConversation({id, title})` → POST `/v1/conversations` → upsert → recrea.
2. **404 = no-op falso** — api/chat/route.ts:631-633: *"treat it as a successful no-op so the sidebar removes the row regardless"*. Casos reales de 404 con fila existente:
   - member + `user_id` resuelto distinto (Clerk user re-creado → nuevo `User.id` en `_resolve_user_id`, conversations.py:115-122) → el listado (member, user_id propio) tampoco la mostraría… salvo transición owner→member o si el chat fue creado con API key (`user_id=None`).
   - **tenant distinto** (org switch): lista en org A, borra en org B → 404 → queda en A.
3. **Revalidación**: `useSWRInfinite` re-fetch en mount (`frontend/hooks/use-active-chat.tsx:233,237` muta la key de history al primer `data` y al `onFinish`; sidebar se remonta al navegar). Si el backend no borró, la fila vuelve.

## 2. TypeError `on_task_metrics` (provider composio/mock)

- `_run_browser_tool` (chat.py:441-500) firma con `*, session_store, binding, on_task_metrics` y llama `browser.run_single(..., on_task_metrics=on_task_metrics)` (chat.py:493-499) **incondicionalmente**.
- `BrowserbaseBrowser.run_single` SÍ acepta `on_task_metrics` (browserbase.py:343, llama en 430-440, propaga en 511/584).
- `ComposioBrowser.run_single` NO lo acepta (composio.py:1049-1062, sin `**kwargs`) → TypeError en el call boundary → `except Exception` (chat.py:500-502) → `{'error': 'BROWSER_ERROR', 'detail': "run_single() got an unexpected keyword argument 'on_task_metrics'"}`.
- `MockBrowser.run_single` tampoco (mock.py:149).
- `ports/browser.py` (BrowserRunnerPort) tampoco declara el callback → el contrato está roto.
- Config actual: `backend/.env` `BROWSER_ENABLED=true`, `BROWSER_PROVIDER=composio` → el path browser del stream está roto HOY. El smoke del cambio previo (apply-progress.md) documenta 403 Composio vía ruta pipeline/wizard (`_handle_wizard_pipeline` chat.py:700-715/775-790, que llama `_procesar_cliente_pipeline` sin on_task_metrics) — no cubre el dispatch de una sola tool por stream.
- Test que sí modela el contrato: `tests/test_chat_stream.py:94-113` mockea `run_single` CON `on_task_metrics` — diverge del provider real composio.

## 3. Telemetría de sesiones — estado y gap

- `use-agent-sidebar.ts:39-44` — SWR con fetcher `null`: memoria efímera, sin storage. `open()` (53-78) crea sesión con `buildSubtasksForTool(toolKey)` (7 tasks default para consultaarca/calendario).
- `data-stream-handler.tsx:135-166` — mapea `data-agent-browser-step`/`data-agent-session-*` del stream a tasks; solo emite para tools browser/stream.
- `use-active-chat.tsx:292-300` — `hydrate(chatId, chatData.activity)`; `api/messages/route.ts:74-76` hardcodea `activity: []` ("the backend does not persist it on the conversation yet").
- `backend/db/queries.ts:715` — `chat.agentActivity` se escribe SOLO en el mock deprecated `.data/db.json` (mock store, "no longer wired", queries.ts:30-51). No llega a Postgres.
- `dashboard/derive.ts:12-23` — KPIs (agentRuns, browserSessions=0 fijo, totalSpendCents) derivados del mismo estado efímero.
- Engine tools: `_run_engine_tool` (chat.py ~500+) no emite eventos de sesión → `consultaarca` invisible en agent-sessions.

## 4. Tema — dark landing

- `app/layout.tsx:119-125`: `<ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>`.
- `app/(landing)/layout.tsx` — passthrough (solo `{children}`).
- Toggle: `sidebar-user-nav.tsx:35`; consumo: `sheet-editor.tsx:23`.
- `globals.css:5` custom-variant dark; `.dark` vars L100+; media-query dark L234-242 solo pisa vars legacy RGB (no aplica la clase).
- Landing: componentes bajo `frontend/components/landing/*` usan tokens semánticos (`text-muted-foreground`, `bg-foreground/[0.02]`) sin `dark:` literales → se ven dark porque `.dark` está en `<html>`.

## 5. Contrato de datos actual (para la propuesta)

| Fuente | Estructura | Persistencia |
|---|---|---|
| `AgentSession` (agent-execution.ts) | agentId, toolName, messageId, status, tasks[], totalCostCents, startedAt/CompletedAt, liveUrl, windowMs | memoria SWR |
| `browser_sessions` (0005) | provider, context_id, session_id, profile_id, status, proxy_bytes, duration_ms, cost_cents, started/completed, last_used_at, expires_at, tenant, user? | Postgres (solo Browserbase) |
| `conversations.agentActivity` | campos: messages snapshot + activity array | mock deprecated `db.json` |
| agent-sessions page | sessionId (messageId), profileId ("—"), startedAt, duration, cost, status/última task | derivada en vivo |

## 6. Notas de riesgo para verify

- Cualquier cambio en `_run_browser_tool` debe cubrir: composio, browserbase, mock (el contrato `BrowserRunnerPort` no declara `on_task_metrics`).
- El test `test_chat_stream.py` asume `run_single(on_task_metrics=...)` — ajustar junto al fix.
- Prueba de regresión del delete: borrar chat abierto, mandar mensaje nuevo, esperar reappear (hoy reaparece).
- La migración nueva no debe chocar con `a3183d34be98_billing_tokens_saas_schema` ni `0006_generated_pdfs_bytes` (orden de revisión previa).