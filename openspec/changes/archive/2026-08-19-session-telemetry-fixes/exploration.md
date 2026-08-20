# Exploration — session-telemetry-fixes

## Pregunta / Request

1. **Las sesiones de agente no se ven** — `consultaarca` (engine determinístico, sin browser) y, en general, las ejecuciones de agentes no dejan telemetría persistida: la página "Sesiones de agentes" queda vacía o se pierde al recargar.
2. **Columna "Acciones" muestra solo "-"** — la tabla de sesiones (agente/browser) no tiene datos de acciones/tasks persistidos.
3. **Deleción de conversaciones** — una conversación borrada del sidebar vuelve a aparecer.
4. **Tema** — la landing debería quedar siempre en light, hoy hereda dark por el `ThemeProvider` raíz con `defaultTheme="system"`.

## Estado actual (verificado en código)

### Telemetría de sesiones de agente

- **No existe telemetría backend para engines determinísticos.** `backend/agente_fiscal/telemetry.py` es Sentry-only. El tipo de dominio vive en TS: `backend/ai/tools/agent-execution.ts` (`AgentSession`, `AgentTask`, statuses, `startedAt/completedAt/totalCostCents`, `liveUrl`).
- **El estado de sesiones es 100% client-side y efímero**: `frontend/hooks/use-agent-sidebar.ts` guarda sesiones en SWR en memoria (key `{tenant|personal}:agent-sidebar`, fetcher `null` → sin persistencia, sin localStorage). Se pierde al recargar.
- **El intento de rehidratar existe pero está cortado**: `frontend/hooks/use-active-chat.tsx:292-300` llama `hydrate(chatId, chatData.activity)`; pero `frontend/app/(chat)/api/messages/route.ts:74-76` devuelve **`activity: []`** con el comentario explícito: *"the backend does not persist it on the conversation yet"*. → `hydrate` nunca corre.
- **UI de tabla**: `frontend/app/(chat)/agent-sessions/page.tsx` (client-only, `allSessions` de `useAgentSidebar`) + `frontend/components/remote-browser/remote-browser-table.tsx` (usa `useRemoteBrowsers`). Los headers salen del i18n dict (`frontend/i18n/dictionary.ts:1500-1523` — `sessionId: "ID de sesión"`, etc.). **No existe clave "Acciones"** en el dict; el placeholder "—" sale de helpers (`getProfileName` L35, `getTaskSummary` L56, `frontend/components/chat/agent-sidebar.tsx:79,96,415`). La columna que el usuario llama "Acciones" probablemente sea la de estado/tasks o el dato `task.label` que hoy es solo el paso streamed en vivo.
- **Backend stream emite telemetría solo para una herramienta**: el branch browser (`_run_browser_tool`, `backend/agente_fiscal/api/routes/chat.py:441-500`) recibe callbacks (`on_live_url`, `on_step`, `on_task_metrics`); las tools engine (`_run_engine_tool`, línea ~500+) **no emiten ningún evento de sesión**. `consultaarca` corre por `_run_engine_tool` → sin `data-agent-session-*`, sin tasks, sin costos.

### Persistencia de sesiones de browser (solo Browserbase)

- Tabla `browser_sessions` (migración `backend/alembic/versions/0005_browser_sessions.py`; ORM en `backend/agente_fiscal/db/models/business.py`; port `backend/agente_fiscal/ports/browser_sessions.py`; repo `backend/agente_fiscal/adapters/db_browser_sessions.py`).
- Wiring de persistencia: `backend/agente_fiscal/api/routes/chat.py:1540-1610` — `_persist_task_metrics` (encola `task_metrics` → `session_store.release/create`). **Solo corre si `session_store` está seteado** (Browserbase).
- **BUG real encontrado**: `_run_browser_tool` pasa `on_task_metrics=on_task_metrics` (chat.py:499) **incondicionalmente**, pero SOLO `BrowserbaseBrowser.run_single` lo acepta (`backend/agente_fiscal/adapters/browser/browserbase.py:343,430,440`). `ComposioBrowser.run_single` (`backend/agente_fiscal/adapters/browser/composio.py:1049-1062`) y `MockBrowser` (`adapters/browser/mock.py:149`) NO lo aceptan → **`TypeError: unexpected keyword argument 'on_task_metrics'`** → `except Exception` → `BROWSER_ERROR`. `backend/.env` fija `BROWSER_PROVIDER=composio` y `BROWSER_ENABLED=true` → con la config actual, **cualquier tool browser vía stream falla con TypeError** (el smoke test del cambio previo no lo detectó porque usó la ruta wizard/pipeline que no pasa el callback; el 403 Composio documentado vino de esa otra ruta).
- `factory.py:35`: composio ignora `session_store`/`binding` (reuso de contexto es solo Browserbase).

### Flujo de borrado de conversación (el bug del "reaparece")

Cadena verificada: `sidebar-history.tsx:145-148` → `DELETE /api/chat?id=X` (fire-and-forget, **sin `await`, sin manejo de error**) → BFF `api/chat/route.ts:608-638` (`deleteConversation`; **404 → respuesta 200 fake "success"**) → backend `DELETE /v1/conversations/{id}` (`api/routes/conversations.py:225-250` → `conversation_repo.delete_conversation` hard-delete).

Rutas de re-materialización (la fila se borra pero vuelve):

1. **Upsert recrea filas borradas.** `conversation_repo.upsert_conversation` (conversation_repo.py:84-93) **crea** la conversación si no existe. Dos callers re-crean tras el borrado:
   - `backend/agente_fiscal/api/routes/chat.py:304` `upsert_conversation(...)` en cada turno del stream → si el chat borrado sigue abierto en la UI y el usuario manda un mensaje, la fila renace.
   - BFF title final: `frontend/app/(chat)/api/chat/route.ts:589` `saveConversation({id, title})` → POST `/v1/conversations` → upsert → recrea.
2. **404 tratado como éxito** (route.ts:631-633): si el backend devuelve 404 por ownership (member con `user_id` distinto/Clerk re-creado) o tenant, el sidebar oculta la fila optimísticamente pero queda en DB → reaparece al revalidar.
3. **Fetch sin manejo de error** (sidebar-history.tsx:145-148): cualquier 5xx/timeout/offline silencia el fallo; el `mutate` optimista ya sacó la fila → reaparece en el siguiente mount/revalidation.

### Tema (dark en landing)

- `frontend/app/layout.tsx:119-133`: `<ThemeProvider attribute="class" defaultTheme="system" enableSystem>` **en la raíz** — la landing (`frontend/app/(landing)/layout.tsx`, passthrough) hereda dark si el SO pide dark.
- `frontend/app/globals.css:5` `@custom-variant dark (&:is(.dark, .dark *))`; vars `.dark` en L100; `@media (prefers-color-scheme: dark)` solo afecta vars legacy RGB (L234-242), no fuerza la clase `.dark`.
- Toggle: `frontend/components/chat/sidebar-user-nav.tsx:35` (`setTheme/resolvedTheme`) y `frontend/components/chat/sheet-editor.tsx:23`. Los componentes de landing usan solo tokens semánticos (sin `dark:` literales) → se aclaran heredando la clase.

## Áreas afectadas

- `backend/agente_fiscal/api/routes/chat.py` — telemetría de sesión para engines (emitir `data-agent-session-*`), fix TypeError `on_task_metrics` en el dispatch browser, upsert que recrea borrados.
- `backend/agente_fiscal/adapters/browser/composio.py` / `mock.py` / `ports/browser.py` — aceptar (o no pasar) `on_task_metrics`; alinear el contrato.
- `backend/agente_fiscal/db/` (nueva tabla o extensión de `browser_sessions`) — persistir sesiones de agente (incl. `consultaarca`).
- `backend/agente_fiscal/api/routes/conversations.py` + `db/conversation_repo.py` — semántica de delete (404→?; no re-crear en title upsert; ownership).
- `frontend/app/(chat)/api/chat/route.ts` — DELETE con manejo real; title-save sin recrear; validar.
- `frontend/components/chat/sidebar-history.tsx` — fetch del delete con `await` + error toast + revalidate.
- `frontend/hooks/use-agent-sidebar.ts` / `use-active-chat.tsx` / `frontend/app/(chat)/api/messages/route.ts` — hydrate desde backend real (campo `activity`).
- `frontend/app/(chat)/agent-sessions/page.tsx` + `frontend/i18n/dictionary.ts` — columna "Acciones" con datos reales (7 defaults por tool / tasks reales).
- `frontend/app/layout.tsx` + `frontend/app/(landing)/layout.tsx` — scoping de light en landing.

## Enfoques

### A. Telemetría persistida de sesiones (consultaarca + browser)

1. **Nueva tabla `agent_sessions`** (tool, message_id, profile_id, status, tasks JSONB, cost_cents, started/completed, tenant, user, created/updated) escrita por el backend en `chat.py` al terminar cada tool (engine y browser), y expuesta vía `GET /v1/agent-sessions` + BFF `/api/agent-sessions`; la página consume real data y el hydrate lee de ahí (o del propio conversation payload).
   - Pros: cubre engines y browser por igual; separa concerns; permite KPIs de dashboard ya derivados (`frontend/lib/dashboard/derive.ts`); la UI solo cambia la fuente de datos.
   - Cons: migración nueva; require decidir granularidad (por tool, por turno); histórico de sesiones ya ocurridas se pierde.
   - Effort: Alto (migración + port + repo + endpoint + BFF + UI + tests).
2. **Extender `browser_sessions`** con `tool_name`, `actions JSONB`, `message_id`, `engine` (no browser, sin proxy).
   - Pros: reusa tabla/repo/migración 0005; menos piezas nuevas.
   - Cons: nombre/contrato desencajado (no es browser); costo y duración sin sentido para engines; mezcla concerns en `db_browser_sessions`.
   - Effort: Medio.
3. **Persistir en `conversation.agentActivity`** (columna JSONB en `conversations` o en mensajes).
   - Pros: la UI ya tiene el hook de hydrate listo (`use-active-chat.tsx`); cero tablas nuevas.
   - Cons: el campo vive hoy solo en el mock deprecated (`backend/db/queries.ts:715`); no modela costos/duraciones agregadas; mezcla datos de sesión con la conversación.
   - Effort: Bajo-Medio.

### B. Fix delete-reaparece

1. **Backend: no re-crear en upserts de título/post-delete + delete 204 real**: `saveConversation({id,title})` debería ir a un endpoint "patch title" que NO cree filas (o `set_conversation_status`-style); el stream upsert ya existente solo persiste mensajes nuevos (queda), pero el delete debe invalidar el estado activo del cliente.
2. **Frontend: borrar el chat activo con navegación/invalidación**: en `handleDelete`, si el chat borrado es el activo, invalidar/navegar; `await` el fetch y tostar error si falla; revalidar la lista solo tras éxito real.
3. **BFF: 404 → no-op true solo si el row realmente no existe** — devolver `{success, deleted:false}` y que el sidebar actúe en consecuencia (hoy el 404 se traga sin distinguir).

Recomendación: combinar 1+2 (el 3 depende de decidir semántica de ownership).

### C. Landing siempre light

1. **Scoping del ThemeProvider**: mover `ThemeProvider` al layout `(chat)` (los únicos consumidores son sidebar-user-nav y sheet-editor, ambos en chat) y fijar la landing light por diseño (CSS tokens base light).
2. **Wrapper light en `(landing)/layout.tsx`**: renderizar `{children}` dentro de `<div className="light">` (next-themes re-aplica vars `.light` solo al subtree; verificar interacción con `@custom-variant dark`).
3. **Enforcar en CSS**: anular vars dark dentro del subtree landing vía selector `.landing-scope` (más frágil).

Recomendación: opción 1 (más limpia), con verificación visual del toggle en chat.

## Recomendación

- **A: Opción 1** (tabla `agent_sessions` nueva) como fuente única de telemetría para engines y browser, escribiendo desde el backend al finalizar cada tool (sin depender de callbacks del provider) y exponiendo endpoint + BFF; la UI de agent-sessions/remote-browser y el `hydrate` pasan a consumirla. Incluye el fix del TypeError `on_task_metrics` (pasar el callback solo cuando el provider lo soporta, o mover el persist al backend post-run).
- **B: 1+2** — delete real con invalidación del chat activo y sin re-creación por título; 404 con semántica honesta.
- **C: Opción 1** — ThemeProvider scoped al layout chat.

## Riesgos

- **Alto**: TypeError `on_task_metrics` con `BROWSER_PROVIDER=composio` (default en `.env`) — hoy las tools browser vía stream devuelven `BROWSER_ERROR`; verificar primero con smoke real.
- **Medio**: migración nueva de `agent_sessions` + sync con `browser_sessions` existente (no duplicar ni divergir).
- **Medio**: cambiar el title-save a "no crear" puede romper el flujo de chat nuevo (el título se setea antes de que el primer turno persista) — confirmar timing.
- **Bajo-Medio**: scoping del ThemeProvider puede alterar el flash de tema en rutas de chat/embed.
- **Bajo**: datos históricos de sesiones (mock `db.json` / SWR efímero) no migran.

## Preguntas abiertas

- ¿La columna "Acciones" es la de estado/tasks de la tabla de agent-sessions (7 acciones default por tool según `buildSubtasksForTool`), o una columna específica en otra vista (dashboard/actions)? Con el teletipo persistido, mostrar la última task real o el conteo "n/tasks" resuelve ambas.
- ¿Las sesiones de agentes deben persistir por tenant/user con ownership (owner/admin vs member) como conversaciones?
- ¿El histórico de `browser_sessions` ya existente debe unificarse en la nueva tabla o convivir?
- ¿Landing light aplica también a rutas embebidas (`/embed/*`) o solo `(landing)`?

## Ready for Proposal

**Yes** — evidencia suficiente para proponer A1+B1+B2+C1. Confirmar antes de proponer: alcance exacto de "Acciones", modelo de ownership, y RUTA de verificación del TypeError (smoke con credenciales reales o unit test del dispatch).