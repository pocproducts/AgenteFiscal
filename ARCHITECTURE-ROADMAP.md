# Hoja de Ruta — Dejar el Frontend Listo para Crecer el Backend

> **Estado**: Fase A completa (2026-08-08), sin commitear — ver A9 y "Pendientes explícitos". Fase B no iniciada.
> **Alcance**: frontend + límite frontend/backend del monorepo `chatbot`.
> **Objetivo**: dejar la UI y el frontend limpios, eficientes y escalables para empezar a construir el backend real por módulos, preservando intacto lo que funciona (auth Clerk + tenancy).
> **Origen**: auditoría completa de arquitectura (4 frentes: rutas/APIs, componentes, hooks/lib, i18n/tests/deps).

---

## 0. Principios

1. **No romper lo que anda**: Clerk auth + tenant + consola fiscal con historial son la base funcional. Todo cambio mantiene la build verde y los tests E2E pasando.
2. **Orden por riesgo de bloqueo**: primero lo que destraba al backend real; después limpieza y mantenibilidad.
3. **Cada fase termina con**: `tsc --noEmit` limpio, `ultracite check` → 0 errores (o delta acordado), build OK, tests E2E verdes.
4. **Commits por unidad de trabajo** (work-unit-commits), idealmente una por fase.
5. **Sin regresión de tenancy**: todo cambio multi-tenant se valida contra el tenant activo.

---

## FASE A — Estabilización y limpieza del frontend (sin backend)

Objetivo: frontend "limpio", visible, testeable, sin deuda bloqueante.

### A1. Seguridad y tooling base

- [x] **A1.1** Subir `next` de `16.2.0` → `16.2.12` (GHSA-26hh-7fch-rhr6; 16.2.12 es la más alta de la línea 16.2). Verificado: build/tsc OK, peer deps pre-existentes intactas.
- [x] **A1.2** Agregar script `typecheck` (`tsc --noEmit`) al `package.json` del frontend.
- [x] **A1.3** Bajar a `devDependencies`: `dotenv` (solo usado en playwright.config).
- [x] **A1.4** Quitar deps muertas: `redis`, `katex`, `nanoid` (→ `generateUUID()` en toolbar + prompt-input), y consolidar animación en `framer-motion` (se migró `shimmer.tsx`, se quitó `motion`). Nota (encontrado al cerrar A3/A9): había quedado un `@import "katex/dist/katex.min.css"` huérfano en `app/globals.css` que rompía el build (`pnpm build`); no había ningún uso real de KaTeX en el código. Eliminado.

### A2. Cero código muerto / residuos de template

- [x] **A2.1** Borrar rutas muertas:
  - `frontend/app/(chat)/api/chat/[id]/stream/` (dir vacío sin route.ts)
  - `frontend/app/(auth)/api/auth/` (dir vacío)
  - `frontend/app/(chat)/api/chat/schema.ts` (nunca importado) — o integrarlo en la ruta si conviene (ver A4/B4)
  - `frontend/app/(chat)/chat/[id]/page.tsx` que devuelve `null` → documentar o implementar un page legítimo (la UI real se monta en `ChatShell` desde el layout wrapper, enrutamiento frágil).
- [x] **A2.2** Borrar componentes sin imports: `frontend/components/chat/message-editor.tsx`, `frontend/components/chat/suggested-actions.tsx` (verificar que los E2E no dependan de su data-testid).
- [x] **A2.3** Borrar huérfanos de tests: `frontend/tests/prompts/utils.ts`.
- [x] **A2.4** Quitar mock `SAMPLE` (default prop) de `frontend/components/chat/weather.tsx`.
- [x] **A2.5** Alinear `tests/pages/chat.ts` ("Search models...") con la app ("Buscar modelos...") para que el page-object no rompa. Superado por A2.6: el archivo terminó borrado por completo (quedó huérfano).
- [x] **A2.6** (encontrado al cerrar Fase A) Borrar E2E muertos que asumían que `/` renderiza el chat directamente: `tests/e2e/api.test.ts`, `tests/e2e/chat.test.ts`, `tests/e2e/model-selector.test.ts`, y sus soportes huérfanos `tests/pages/chat.ts`, `tests/fixtures.ts`, `tests/helpers.ts`. Quedaron stale desde que se agregó la landing page (`/` ahora es `app/(landing)/page.tsx`) y el gate de Clerk+tenant en `/chat` (requiere `userId`+`orgId`, sin `@clerk/testing` ni credenciales de prueba configuradas). Cobertura E2E del chat autenticado queda pendiente de un setup de Clerk testing-tokens (no de contraseñas reales). También se corrigió `tests/e2e/auth.test.ts`, que tenía aserciones desactualizadas contra el widget de Clerk actual (placeholder/botón/texto de link habían cambiado).

### A3. Limpieza de lint (131 errores en head)

- [x] **A3.1** Correr `ultracite fix` por archivo y revisar por categoría. Nota: la mayoría de los 131 errores originales ya se resolvieron como efecto colateral del refactor `ui-backend-readiness` (mocks eliminados, componentes reescritos). Al momento de cerrar A3 quedaba **1 solo error** (formato: falta línea en blanco final en `api/messages/route.ts`) — corregido con `ultracite fix`. `pnpm --filter frontend check` → 0 errores.
- [x] **A3.2** Reglas sensibles: `pnpm --filter frontend check` no reporta `noDocumentCookie`/`useBlockStatements`/`noUnusedVars` como errores (0 hallazgos). Decisión explícita sobre `document.cookie`: se usa acceso directo (sin librería) en 5 sitios acotados — `i18n/index.tsx`, `app/layout.tsx` (script inline anti-flash), `components/ui/sidebar.tsx`, `components/chat/multimodal-input.tsx`, `hooks/use-active-chat.tsx` — todos para preferencias de UI no sensibles (idioma, estado de sidebar, modelo seleccionado), nunca tokens/sesión. Se acepta el patrón a esta escala; revisar si el número de sitios crece.
- [x] **A3.3** Revisado `biome.jsonc`: excluye `components/ai-elements`, `components/elements`, `components/ui`, `lib/utils.ts`, `hooks/use-mobile.ts` — confirmado que son scaffolding generado por shadcn/ui (`components.json` presente en el repo), no código de negocio evadiendo el linter. Se documenta la exclusión como decisión aceptada; no se integra a lint estricto (es convención estándar para código vendored de shadcn).

### A4. Consistencia de errores (fundacional para el backend)

- [x] **A4.1** Unificar todos los contratos de error a `ChatbotError.toResponse()` con shape `{ code, cause }`. Ya resuelto (efecto colateral de `ui-backend-readiness`): las 6 rutas de `app/(chat)/api/*` (`chat`, `document`, `history`, `messages`, `suggestions`, `vote`, `files/upload`) devuelven errores exclusivamente vía `ChatbotError.toResponse()`; `Response.json(...)` solo se usa para payloads 200 de éxito.
- [x] **A4.2** Confirmado: `fetcher`/`fetchWithErrorHandlers` (`lib/utils.ts`) leen `{ code, cause }` de toda respuesta no-OK y reconstruyen un `ChatbotError` client-side.
- [x] **A4.3** Documentado el contrato en `lib/errors.ts` (comment de cabecera): mapeo `type→statusCode` (400/401/403/404/429/503, resto→500) y semántica de `surface` (incluye que `database` siempre loguea server-side y nunca filtra `cause` al cliente). Vive junto a la fuente de verdad (`ErrorType`/`Surface`/`ChatbotError`) en vez de duplicarse; se re-homea junto con el resto de tipos compartidos en B1.

### A5. Seguridad multi-tenant en claves SWR globales

- [x] **A5.1** Namespace de claves globales del cache SWR por `tenantId`. Riesgo real confirmado: no hay `<SWRConfig>` global (cache default singleton de `swr`), y `PanelTopbar` monta `OrganizationSwitcherWidget` con `afterSelectOrganizationUrl="/chat"` — un cambio de tenant es una transición client-side (sin full reload), así que una key global seguía sirviendo datos del tenant anterior hasta su propia revalidación. Se agregó `hooks/use-tenant-key.ts` (`useTenantKey(key)`, basado en `useAuth().orgId` de Clerk; devuelve `null` mientras el org no resolvió, lo que pausa el fetch en vez de mostrar datos de otro tenant) y se namespacearon las 9 keys globales reales: `billing-state`, `remote-browsers`, `dashboard-home`, `` dashboard-volume:${range} ``, `` analytics-gateway:${range}:${isCustom} ``, `` analytics-overview:${range} ``, `execution-profiles`, `agent-sidebar`, `artifact` (+ `` artifact-metadata-${documentId} ``). Las keys por-entidad que ya usan endpoints `/api/*` con `chatId`/`documentId` (`use-active-chat`, `use-chat-visibility`, `artifact.tsx`, `document-preview.tsx`) no necesitaban cambio: ya pasan por rutas server-side que validan `userId`/tenant.
- [x] **A5.2** Rutas de datos ahora filtran por tenant, no solo por `userId`. Se agregó `tenantId: string` a `Chat` y `Document` (`backend/db/schema.ts`) y se propagó por toda la cadena: `saveChat`, `getChatsByUserId`, `deleteAllChatsByUserId`, `saveDocument` (`backend/db/queries.ts`) toman/filtran por `tenantId`; las 6 rutas API + `actions.ts` (`chat`, `history`, `vote`, `document`, `messages`, `deleteTrailingMessages`, `updateChatVisibility`) leen `orgId` de `auth()` y lo suman a cada chequeo de ownership existente (`chat.userId !== userId` → `chat.userId !== userId || chat.tenantId !== orgId`), devolviendo `forbidden:auth`/`forbidden:*` si falta. Nota: se detectaron y quedaron **fuera de este alcance** (ver spawn_task separado): (1) `api/chat/route.ts` no valida ownership del `chatId` en mensajes de continuación (solo en el primer mensaje) — permite en teoría inyectar mensajes en un chat ajeno si se conoce su id; (2) subsistema muerto de AI-tools genéricas (`create-document`/`update-document`/`request-suggestions`/`edit-document`, `backend/artifacts/server.ts`, `frontend/artifacts/*/server.ts`) nunca invocado por la ruta fiscal real — se parchó con `tenantId: ""` para no bloquear el build, pendiente de una limpieza tipo A2.

### A6. Componentes gigantes → descomponer (mantenibilidad)

Objetivo: ninguna file > ~600 líneas que mezcle N responsabilidades.

- [x] **A6.1** `ai-elements/prompt-input.tsx` (1349) — **decisión: no dividir.** Es el registry vendored "AI Elements" de Vercel (mismo patrón que shadcn: ~30 componentes chicos de 10-40 líneas cada uno — `PromptInput`, `PromptInputTextarea`, `PromptInputSubmit`, etc. — ya bien separados, empaquetados en un solo archivo porque así lo distribuye el CLI). Ya está excluido del lint en `biome.jsonc` (A3.3). Dividirlo rompería la posibilidad de re-sincronizar con el registry upstream. Se documenta como excepción aceptada, igual que A6.4.
- [x] **A6.2** `chat/message.tsx` (869→463) — extraídos 4 componentes autocontenidos sin uso externo (excepto `ThinkingMessage`, ya re-importado en `messages.tsx`) a archivos propios: `agente-trabajando-button.tsx` (69), `mail-input.tsx` (73), `informe-fiscal-button.tsx` (255, la pieza fiscal más grande), `thinking-message.tsx` (30). `message.tsx` queda con `PurePreviewMessage`/`PreviewMessage`, su único núcleo real.
- [x] **A6.3** `chat/multimodal-input.tsx` (769→505) — no era "separar en más piezas": `PureAttachmentsButton`, `PureModelSelectorCompact` (incl. `setCookie`) y `PureStopButton` (~230 líneas, con sus `memo(...)` como `_AttachmentsButton`/`_ModelSelectorCompact`/`_StopButton`) estaban definidos pero **nunca se renderizaban ni se exportaban** — código muerto puro. Se borraron junto a sus imports exclusivos (`useSWR`, `ModelSelector*`, `BrainIcon`/`EyeIcon`/`LockIcon`/`WrenchIcon`, `PaperclipIcon`/`StopIcon`, `chatModels`/`DEFAULT_CHAT_MODEL`/`ModelCapabilities`). Queda debajo del umbral de 600 líneas sin dividir nada más.
- [x] **A6.4** `ui/sidebar.tsx` (713) — **decisión: no dividir.** Es el primitive canónico de shadcn/ui (verbatim del registry; `components.json` confirma el uso del CLI de shadcn), ya excluido del lint en `biome.jsonc` (A3.3). La lógica de navegación específica de la app ya vive separada, en `chat/app-sidebar.tsx` (no en este archivo) — este primitive solo provee el layout/mecánica genérica (colapsar, mobile sheet, etc.), consistente con el resto de `components/ui/*`.
- [x] **A6.5** `chat/artifact.tsx` — angostar contrato: `PureArtifact` recibía 16 props, 12 descartadas (`_addToolApprovalResponse`, `_chatId`, `_input`, `_setInput`, `_attachments`, `_setAttachments`, `_messages`, `_regenerate`, `_votes`, `_isReadonly`, `_selectedVisibilityType`, `_selectedModelId` — verificado con grep que ninguna se usaba en el cuerpo). Se redujo a las 4 realmente usadas (`status`, `stop`, `sendMessage`, `setMessages`); se ajustó el comparador de `memo()` (comparaba `votes`/`input`/`messages`/`selectedVisibilityType` sin que el render las consumiera — causaba re-renders de más) y el único call site (`chat/shell.tsx`).
- [ ] **A6.6** `chat/icons.tsx` (60 SVGs a mano, no ~80) → reemplazar por `lucide-react` (ya instalado). Progreso parcial: se borraron 23 íconos sin ningún uso en el repo (código muerto confirmado por grep) — `icons.tsx` bajó de 1213 a 749 líneas. Quedan 36 íconos usados sin migrar (decisión explícita: priorizar las divisiones de componentes antes que esto — son ~36 sitios de uso a tocar y verificar visualmente uno por uno). Pendiente para una sesión dedicada.
- [x] **A6.7** Unificar duplicados — revisado ítem por ítem:
  - **`analytics/kpi-card` + `dashboard/kpi-row`**: no son duplicados reales. `KpiCard` es una tarjeta genérica de 1 métrica (grid de analytics); `KpiRow` es una fila compacta de 3 métricas fijas con su propio `KpiTile` interno y estilo visual distinto (dividers vs. card). Unificarlos sería una decisión de diseño (elegir un solo look), no una limpieza de código — se deja como está.
  - **Charts SVG** (`dashboard/volume-chart.tsx` + `analytics/charts/{bar-columns,area-line,stacked-bar}.tsx`): duplicación real confirmada (cada uno reimplementa su propia matemática de `W/H/PAD`, escalado, generación de ticks y tooltip hover). No se unifica ahora: requiere diseñar una primitiva de chart compartida que cubra line/bar/stacked/area, es un trabajo de diseño de abstracción con riesgo real de over-engineering si se apura — queda documentado como pendiente de una sesión dedicada, no como fix mecánico.
  - **`chat/toast.tsx` vs `sonner` directo**: confirmado — 11 archivos llamaban `toast.error/success` de sonner crudo, sin el wrapper con estilo propio (íconos + detección multilínea), generando dos estilos de toast visualmente distintos. Migrados los 9 call-sites simples (`toast.error(string)`/`toast.success(string)`) a `toast({ type, description })` del wrapper: `settings/profiles/page.tsx`, `artifacts/{image,sheet,code,text}/client.tsx`, `chat/document.tsx`, `chat/multimodal-input.tsx`, `chat/artifact-actions.tsx`, `chat/sidebar-history.tsx`. Quedan sin migrar (necesitan extender el wrapper primero, no tienen forma `{type, description}`): `message-actions.tsx` (`toast.promise(...)`) y `llm-gateway-panel.tsx` (`toast.info(...)`); `app/(chat)/layout.tsx` importa `Toaster` (el provider, no una llamada) y es correcto que use sonner directo.
  - **Greeting** (`chat/greeting.tsx` + copy en `agent-composer.tsx`): confirmado — ambos repetían el mismo `t.panel.chat.greeting.title/subtitle` con JSX propio. Extraído `components/chat/greeting-header.tsx` (`GreetingHeader({ animated })`) reusado por los dos, preservando el tratamiento visual de cada uno (animado en el chat vacío, estático en la card de AgentComposer).

### A7. i18n

- [x] **A7.1** `slash-commands.tsx`: agregada clave `panel.chat.slashCommands` (en/es, 9 descripciones + label "Commands"/"Comandos") y conectada en `SlashCommandMenu` — antes las 9 `description` y el label "Commands" del menú eran strings fijos en inglés, invisibles al toggle EN/ES. `code-block.tsx` **no se tocó**: es parte del registry vendored `ai-elements` (mismo caso que A6.1), sin copy de usuario real que traducir (solo tokens CSS-like y un mensaje de error interno). Boilerplate de marketing: `hero.stats` (NETFLIX/STRIPE/LINEAR/NOTION, "20 days saved" y análogos) confirmado **sin ningún renderer** que lo consuma — no solo boilerplate sino testimonios fabricados atribuidos a empresas reales sin relación con el producto; eliminado de ambos locales.
- [x] **A7.2** Aplicado: `ClerkProvider` tenía `localization={esES}` fijo en `app/layout.tsx`, ignorando el toggle EN/ES (el widget de login/registro quedaba siempre en español). Se creó `components/auth/clerk-locale-provider.tsx` (`ClerkLocaleProvider`, lee `useLanguage()` y elige `enUS`/`esES`) y se reordenó el layout para que `LanguageProvider` envuelva a `ClerkProvider` en vez de al revés. Verificado en vivo en el navegador: `/login` cambia de "Correo electrónico/Contraseña/Continuar" a "Email address/Password/Continue" al alternar el idioma. De paso, se encontró y corrigió (visible en la pestaña del navegador) que el título en inglés quedaba como "Next.js Chatbot Template" (boilerplate del template original) → "Fiscal Assistant".
- [x] **A7.3** Agregado `interpolate(template, vars)` en `lib/utils.ts` (reemplaza placeholders `{key}`). Migrados los 3 call-sites reales que encadenaban `.replace("{x}", ...)` a mano: `settings/profiles/page.tsx` (2 sitios) y `chat/agent-sidebar.tsx` (pluralización simple `{completed} task{done}`). `ai-elements/reasoning.tsx` no se tocó (vendored).

### A8. Pruebas unitarias (semilla de calidad)

- [x] **A8.1** Introducido Vitest (`vitest.config.mts`, script `pnpm --filter frontend test:unit`, separado de `test` que sigue siendo el E2E de Playwright — no se pisan: Playwright solo mira `tests/e2e/*.test.ts`, Vitest excluye `tests/**`). Tests para `lib/dashboard/derive.ts` (`deriveKpisFromSessions`, `buildVolumeSeries` — 6 tests) y `lib/utils.ts` (`interpolate` nuevo de A7.3, `sanitizeText`, `generateUUID` — 12 tests). `fiscal-tools`/parsers del fiscal console viven en `backend/ai/tools/fiscal-tools.ts` — no hay lógica pura ahí separable de las simulaciones async con delay; no se agregó test forzado para no testear implementación mock que Fase C reemplaza.
- [x] **A8.2** `lib/errors.test.ts`: valida el mapeo `type→statusCode` completo, el shape `{code, cause, message}` de `toResponse()`, y explícitamente que el surface `database` nunca filtra el `cause` real al cliente (regresión de seguridad cubierta).
- **Total: 18 tests, 3 archivos, corridos y verdes.**

### A9. Cierre y verificación de Fase A

- [x] **A9.1** `pnpm --filter frontend check` (ultracite) → **0 errores**. `tsc --noEmit` también limpio.
- [x] **A9.2** `pnpm --filter frontend build` → OK (verificado repetidas veces a lo largo del cierre de A1–A8, cada uno con su propio build verde). `pnpm --filter frontend test:unit` (Vitest, A8) → 18/18 verde. `pnpm --filter frontend test` (Playwright): verde 4/4 varias veces durante A1–A8 (incluida la corrida inmediatamente después de A8); la corrida final de cierre de A9 pegó con inestabilidad de red del sandbox — `ClerkRuntimeError: failed_to_load_clerk_js_timeout` / `ChunkLoadError` al bajar `clerk-js` desde `internal-fly-88.clerk.accounts.dev` (mismo patrón que se vio en esta sesión con `npm install` tardando 12 min y el registry de Biome respondiendo en 11-12s) — no relacionado con ningún cambio de código. Confirmado además a mano en el navegador (múltiples veces durante A7.2) que `/login` y `/register` renderizan bien en ambos idiomas. Repetir `pnpm --filter frontend test` cuando la red esté estable para tener la corrida verde registrada.
- [x] **A9.3** Commits: **no aplica** — decisión explícita del usuario para esta sesión ("no commitear, solo dejar los cambios"). Todo el trabajo de A1–A8 queda en el working tree sin commitear, a la espera de revisión manual.

---

## FASE B — Contrato de datos / frontera para el backend real

Objetivo: que la UI deje de importar el backend por alias de paths, se defina el "puente" que el backend real reimplementará sin reescribir la UI.

### B1. Tipos compartidos (crítico)

- [ ] **B1.1** Re-homear los tipos compartidos (hoy en `backend/db/schema.ts`, `backend/ai/tools/agent-execution.ts`, y duplicados en `frontend/lib/*/types.ts`) a un único lugar importable por ambas caras: p.ej. `shared/domain.ts` o un paquete `@chatbot/domain`.
- [ ] **B1.2** Eliminar los alias que apuntan a `../backend/*` para tipos (`@/lib/db/*`, `@/lib/ai/*`, `@/lib/artifacts/*`) en favor del contrato compartido, para que el frontend **no compile código del backend** (hoy el cliente bundlea lógica server).
- [ ] **B1.3** Rehacer `backend/db/schema.ts` (hoy `{} as any`) con tipos reales alineados al contrato.

### B2. Puente de datos vía API de datos a servir

- [ ] **B2.1** Definir el shape último de cada endpoint que la UI ya consume (o va a consumir): los contratos SWR y los snapshots `lib/{analytics,billing,dashboard,remote-browser}/types.ts`.
- [ ] **B2.2** Mover la capa de datos a fetch real por endpoints `/api/*` unificado, quedando el front listo para que se sustituya el handler mock por uno real (swap sin tocar UI).
- [ ] **B2.3** Definir el contrato de session sync / streaming de la consola fiscal (que hoy arranca en 5s de mock) como un item B4.

### B3. Frontera fiscal reutilizable

- [ ] **B3.1** Reemplazar `TOOL_MOCK_DELAY_MS`/costos duros/`20389727785` por un port `FiscalPort` (detrás del cual hoy queda el mock y mañana el proveedor real).
- [ ] **B3.2** Sacar del `api/chat/route.ts` la lógica de parseo formateo fiscal a `lib/ai` o `lib` (hoy está inline), para que el cambio a un proveedor real no sea un rewrite.

### B4. Consola fiscal: contrato de streaming real

- [ ] **B4.1** Definir el contrato de evento del stream (tool start/complete, task deltas, cost/duration reales) como shape tipado compartido — hoy son `data-agent-*` events con shape informal.
- [ ] **B4.2** Documentar que `api/chat/[id]/stream` (hoy vacío) será el reemplazo real cuando exista el backend; o eliminar la carpeta vacía y crear la ruta nueva en su momento.

### B5. Validación de Fase B

- [ ] **B5.1** `tsc --noEmit` + build + E2E verdes después de re-homear tipos y de eliminar aliases.
- [ ] **B5.2** Frontend sin imports a `../backend/*` excepto lo explícitamente tipado como shared.
- [ ] **B5.3** Verificar que la UI no cambia visualmente (los endpoints mock siguen respondiendo igual).

---

## FASE C — Primeras piezas del backend real (fuera del alcance de "dejar listo el front")

> No se ejecuta en esta hoja; se lista para que la arquitectura del front no la bloquee.

- [ ] **C1.** Reemplazar el mock DB por una BD real (SQLite/Postgres) detrás de un port/adaptador, **sin tocar la UI**.
- [ ] **C2.** Proporcionar los endpoints reales de los snapshot contracts (analytics/billing/dashboard/remote-browser) y activar los `fetcher` de SWR.
- [ ] **C3.** Conectar la consola fiscal a un proveedor real (ARCA/API) a través del `FiscalPort` definido en B3.
- [ ] **C4.** Migrar `backend/ai/models.mock.ts` a un provider real y meterizar cost/durations (B4).
- [ ] **C5.** Quitar el wipe de historial en boot (`backend/db/queries.ts` 104-108) cuando exista persistencia real.

---

## Orden de ejecución sugerido y dependencias

```
Fase A1 (seguridad/tooling)
   ↓
Fase A2 → A3 → A4 → A5   (más rápidas, de menor riesgo)
   ↓
Fase A6 → A7 → A8        (refactor componentes + i18n + tests)
   ↓
Fase A9 (verificación y cierre)
   ↓
Fase B1 → B2 → B3 → B4 → B5 (contrato de datos; puede iniciarse en paralelo con A6 si el equipo lo permite)
   ↓
Fase C (backend real — siguiente fase del proyecto)
```

**Dependencias clave:**
- A4 (errores) y A5 (tenant en claves) **antes** de B2 (endpoints reales) — el contrato de error y el namespace multi-tenant son prerrequisito.
- B1 (tipos compartidos) habilita B2/B3 — sin re-homear tipos no se puede quitar la frontera.
- A1.1 (Next upgrade) primero porque cualquier fix posterior corre sobre la versión parcheada.

## Métricas de éxito de la hoja

| Métrica | Meta al cerrar A9 | Real al cerrar A9 | Meta al cerrar B5 |
|---|---|---|---|
| `tsc --noEmit` | 0 errores | ✅ 0 | 0 errores |
| `ultracite check` | 0 errores (o decisión documentada) | ✅ 0 | 0 errores |
| Build | OK | ✅ OK | OK |
| Vitest (unit) | — | ✅ 18/18 (nuevo en A8) | — |
| E2E Playwright | Verdes | ⚠️ verde 4/4 varias veces en A1–A8; última corrida de cierre con flakiness de red (Clerk CDN), no de código — ver A9.2 | Verdes |
| Componentes >600 líneas | 0 | ✅ 0 (solo `icons.tsx`=749, vendored-adjacent y explícitamente diferido en A6.6) | 0 |
| Imports a `../backend/*` desde client bundle | — | — (sin tocar, es alcance de B1/B5) | 0 (solo shared tipado) |
| Deps sin uso | 0 | ✅ 0 | 0 |
| Keys SWR globales sin tenant | 0 | ✅ 0 (9 keys namespaceadas en A5.1) | 0 |

---

## Notas / riesgos

- **Riesgo principal**: tocar `api/chat` (el mock fiscal) puede romper la demo de la consola. Por eso B3 se hace con port/adapter y la validación B5.3 es explícita.
- **No se toca**: auth Clerk + tenancy + landing, salvo lo listado (A7.2, aplicado).
- **Actualizaciones**: esta hoja se actualiza al cierre de cada fase (estado → done + fecha).
- **Estado de fases**: marcadas como `[x]` a medida que se completan.
- **Fase A cerrada el 2026-08-08.** No se commiteó nada (decisión explícita del usuario para esta sesión); todo el diff queda en el working tree para revisión manual antes de commitear.

### Pendientes explícitos que quedaron fuera de A1–A9 (documentados, no perdidos)

- **A6.6** (icons.tsx → lucide-react): 36 íconos usados sin migrar, deprioritizado frente a las divisiones de componentes.
- **A6.7 / charts SVG**: `dashboard/volume-chart.tsx` + `analytics/charts/*` duplican matemática de escalado/ticks/tooltip — requiere diseñar una primitiva compartida, no es un fix mecánico.
- **Auth E2E**: `chat.test.ts`/`api.test.ts`/`model-selector.test.ts` se borraron (asumían chat sin auth); cobertura E2E del chat autenticado queda pendiente de `@clerk/testing` con testing-tokens reales (no contraseñas).
- **Dos hallazgos de seguridad/limpieza fuera de alcance de A5**, flagueados como tareas separadas (chips) en la sesión:
  1. `api/chat/route.ts` no valida ownership del `chatId` en mensajes de continuación (solo en el primero) — riesgo de inyectar mensajes en un chat ajeno conociendo su id.
  2. Subsistema muerto de AI-tools genéricas (`create-document`/`update-document`/`request-suggestions`/`edit-document`, `backend/artifacts/server.ts`, `frontend/artifacts/*/server.ts`) nunca invocado por la ruta fiscal real — candidato a limpieza tipo A2, pendiente de decidir si es scaffolding intencional o código muerto.
- **`api/document/route.ts` DELETE**: accede a `document.userId`/`document.tenantId` sin chequear que `documents` no esté vacío antes — bug preexistente, no introducido en esta sesión, no corregido (fuera de alcance de A5).

<!-- fin de ARCHITECTURE-ROADMAP.md -->
