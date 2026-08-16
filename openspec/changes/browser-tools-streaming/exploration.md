# Exploration — browser-tools-streaming

## Pregunta
Generalizar el mecanismo UI + conexión de Sistema Registral (browser live embebido + tasks streaming SSE) a todas las tools de browser, cambiando solo las indicaciones/templates ya preparadas por tool. `enviar mail` queda fuera del mecanismo.

## Flujo actual (Sistema Registral, verificado en código)

1. **BFF** `frontend/app/(chat)/api/chat/route.ts` (L145-150): gate `isRegistroRegistralCommand` = `/\bsistemaregistral\b/i` → abre `data-agent-session-start` (agentId, toolName, toolKey, tasks:[], windowMs) y llama `POST /v1/chat/message/stream`.
2. **Backend stream** `backend/agente_fiscal/api/routes/chat.py` `chat_message_stream` (L846-993): `detect(context)` → `Intent.SISTEMA_REGISTRAL` → branch dedicado con `asyncio.Queue` + callbacks `_progress`/`_on_live_url`/`_on_step` → `asyncio.to_thread(_handle_sistemaregistral, ...)`.
3. **Handler** `_handle_sistemaregistral` (L343-404): `build_browser_tasks(with_registro=True)` → `ComposioBrowser.run_single` → `_run_single` (composio.py L391-620): por task → CREATE_TASK → GET_SESSION (→ `on_live_url(liveUrl)`) → WATCH_TASK con polling `current_step` (→ `on_step`, gap-fill por paso L311-336) → `parse_output` → TaskResult → `_consolidate` → `DeudaOutput` (registro, facilidades, deudas, live_url, error).
4. **Eventos SSE exactos:** `conversation_start` `{conversation_id}` · `progress` `{message}` · `live_url` `{url}` · `agent_step` `{step, goal, url, status}` · `complete` `{reply, data, conversation_id}` (L974-986).
5. **BFF mapea** (route.ts L376-481): `live_url`→`data-agent-session-liveurl`; `agent_step`→`data-agent-browser-step`; `complete`→texto + `<details>Datos</details>` (si no error) + espera del window restante (10 min) → `data-agent-session-complete` (o `{status:"error"}` si `data.error`).
6. **UI** `data-stream-handler.tsx` + `agent-sidebar.tsx`: 100% genéricos — remapeo server/local agentId, dedupe de steps, `TOOL_URLS` cubre las 6 tools. **Sin cambios requeridos.**

## Herramientas por estado real

| Tool | Task+Template backend | Intent router hoy | BFF monitor | Estado |
|---|---|---|---|---|
| sistemaregistral | ✅ `RegistroTask`+`TEMPLATE_REGISTRO` | ✅ `SISTEMA_REGISTRAL` | ✅ flow completo | Único conectado |
| deudavencimientos | ✅ `VencimientosDeudasTask`+`TEMPLATE_FULL` | ❌ (solo via REPORTE_COMPLETO/wizard) | ❌ | Task lista, sin acceso directo |
| misfacilidades | ✅ `FacilidadesTask`+`TEMPLATE_FACILIDADES` | ❌ ibíd. | ❌ | Task lista |
| rentascordoba | ✅ `IIBBTask`+`TEMPLATE_IIBB_CORDOBA` | ❌ ibíd. | ❌ | Task lista |
| consultaarca | ❌ sin task/template | ❌ | ❌ | Solo stub mock TS |
| calendariovencimientosarca | ⚠️ sin browser; existe `POST /v1/calendar` (rules_engine + calendario_afip.json) | ❌ | ❌ | Endpoint estático separado |
| informefiscal | Agregador (mock TS) | ❌ | ❌ (excluido en message.tsx L166-172) | Decisión de producto |
| enviarmail | SMTP/Resend sin browser | ❌ | ❌ (excluido) | **Fuera por diseño** |

## Gaps por capa

- **Backend intent**: `Intent` enum solo UNKNOWN/TAXPAYER_QUERY/REPORTE_COMPLETO/SISTEMA_REGISTRAL; `detect()` solo reconoce keywords de sistemaregistral/reporte/consulta. Faltan intents/keywords para las tools browser (riesgo de colisión con TAXPAYER_QUERY). `_ACTION_NAMES` mapea solo 3.
- **Backend stream**: branch SISTEMA_REGISTRAL 100% hardcodeado a `_handle_sistemaregistral` + `format_registro_response`. El SSE framing (queue + callbacks + generator) es reutilizable tal cual; falta dispatch declarativo tool → (task flags, handler, formatter).
- **Backend tasks/templates**: listas para deuda/facilidades/registro/iibb-cba; **faltan** templates NL para consultaarca y calendariovencimientosarca. Formatters: existe `format_registro_response` y `format_reporte_response`; faltan formatters standalone por tool. `DeudaOutput` ya soporta todas las tasks.
- **Frontend BFF**: `isRegistroRegistralCommand` es el único gate; `data-agent-session-start` hardcodea toolName/toolKey; el resto del branch es genérico y reutilizable. Mocks `ejecutar*` en `fiscal-tools.ts` quedan obsoletos para tools con backend real.
- **Frontend UI**: sin gaps. `buildSubtasksForTool` cubre 5 tools; message.tsx ya excluye enviarmail/informefiscal del botón.

## Recomendación de alcance

- **Fase 1 (bajo riesgo):** `deudavencimientos`, `misfacilidades`, `rentascordoba` — ya tienen task+template+parser reales; solo falta wiring (intent → dispatch stream → formatter → gate BFF).
- **Fase 2 (requieren templates nuevos):** `consultaarca` (template de obligaciones; alternativa: reusar consulta padrón que ya hace TAXPAYER_QUERY sin browser) y `calendariovencimientosarca` (template browser o exponer engine `/v1/calendar` existente).
- **Fuera:** `enviarmail` (SMTP, sin browser — explícito) y `informefiscal` (agregador — confirmar con producto).

## Riesgos

- **Alto — Costo/sesiones Composio**: N tools = N sesiones cloud pagas; window de 10 min mantiene la sesión viva.
- **Alto — Ventana vs timeout**: `AGENT_SESSION_WINDOW_MS` = 10 min pero `FacilidadesTask.timeout = 900s` (15 min) — la UI cierra mientras el backend sigue; alinear window por tool.
- **Medio — Error por tool**: mapeo BROWSER_ERROR → estado SSE existe, falta por-tool.
- **Medio — Templates nuevos (consultaarca/calendario)**: calidad no garantizada; calendario tiene alternativa determinística `/v1/calendar`.
- **Medio — Colisión de intents**: keywords nuevas pueden chocar con TAXPAYER_QUERY/REPORTE_COMPLETO; orden de prioridad + keywords específicas.
- **Bajo — Divergencia mocks TS**: `fiscal-tools.ts` seguirá siendo fuente para tools sin backend real.
- **Bajo — Sesiones compartidas**: cada tool entra con login propio (needs_auth=True), encarece corridas multi-tool.

## Recomendación técnica

Mapa declarativo `ToolSpec`: `tool_key → (intent keywords, build_browser_tasks flags, formatter)` compartido por endpoints stream/no-stream/wizard. En BFF, reemplazar `isRegistroRegistralCommand` por set/trie de tool keys y parametrizar toolName/toolKey del `data-agent-session-start`. La UI no entra al cambio.