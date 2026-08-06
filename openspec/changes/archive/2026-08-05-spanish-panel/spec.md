# Spanish Panel Specification

## Purpose

Extiende `lib/i18n` (LanguageProvider/useLanguage, `localStorage optimus-lang`) de `app/(landing)` a `app/(auth)` y `app/(chat)`. Toda la UI copy del panel y auth pasa a un diccionario EN/ES con default `es`, `html lang` dinámico, y toggle global. Contenido generado por IA (prompt del modelo) queda fuera de alcance.

## Capability: i18n-panel

### Requirement: Auth en español por defecto

El sistema MUST renderizar login/register (labels, placeholders, botones, toasts/errores de validación, auth actions) en español por defecto. El provider SHALL estar en la raíz del app con default locale `es`.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|------|
| Default es | Usuario nuevo navega a `/login` | Authentication layout renderiza | Labels, placeholders y botones se muestran en español |
| Acción auth es | Usuario envía credenciales inválidas | Auth action dispara error | Toast/mensaje de validación aparece en español |

### Requirement: Locale global del panel

El panel autenticado (sidebar, header, dialogs, toasts/sonner, skeletons, empty states, settings, analytics, agent-sessions, remote-browser) MUST reflejar el locale activo EN/ES.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|------|
| Panel sigue locale | Locale activo `es` | Panel autenticado renderiza | Todos los strings UI muestran español consistente |
| Switch EN | Locale activo `en` | Panel renderiza | Strings UI muestran inglés, sin mezcla parcial |

### Requirement: Persistencia y documento del locale

Al alternar EN/ES el sistema MUST persistir el locale en `localStorage optimus-lang`, definir `documentElement.lang` y metadata según locale, y MUST NOT mostrar flash de idioma ni double-render (handling SSR).

| Scenario | Given | When | Then |
|----------|-------|------|------|
| Persistencia | Usuario alterna a `es` | Toggle persiste | `localStorage optimus-lang="es"`, `html lang="es"` y metadata correcta |
| Sin flash | Ruta panel carga con `es` almacenado | Hydratación completa | No se ve texto EN previo ni doble render |

### Requirement: Contenido IA fuera de alcance

El sistema MUST NOT traducir contenido generado por el modelo (mensajes del asistente en chat). Solo la UI copy se traduce. Sugerencias/greetings y strings generados por UI SHALL traducirse.

| Scenario | Dado | Cuando | Entonces |
|----------|------|--------|----------|
| Prompt intacto | Asistente responde en chat | Mensaje se renderiza | Contenido IA queda tal cual el modelo lo generó (sin traducción) |
| Strings UI es | Sugerencia/greeting generado por UI | Panel en `es` | String se muestra en español |

## Capability: panel-ui-es

### Requirement: Auth copy es

Auth copy MUST estar 100% en español por defecto, incluyendo login/register y auth layout (ej. "Powered by / AI Gateway").

| Scenario | Given | When | Then |
|----------|-------|------|------|
| Auth layout es | Login `es` | Layout renderiza | "Powered by / AI Gateway" y copy aparecen en español |

### Requirement: Layout del panel es

Layout SHALL traducir sidebar nav items, tooltips, labels, user-menu, visibility selector, submit-button loading, estados de document/image-editor y confirm dialog.

| Scenario | G | When | Then |
|----------|---|------|------|
| Nav es | Sidebar `es` | Renderiza | Nav items, tooltips y labels en español |
| Confirm es | Usuario elimina elemento | Confirm dialog abre | Texto del dialog en español |
| Loading es | Submit con carga | Botón muestra estado | Loading text del submit-button en español |

### Requirement: Chat & AI elements es

Chat/AI MUST traducir message.tsx, tool, reasoning ("Thinking...", "Thought for X seconds"), message-actions (upvote/copy toasts y tooltips), prompt-input aria-labels/placeholders y model-selector placeholder ("Search models..."/"Buscar modelos..."). Nombres de providers propios (Mistral, DeepSeek, Moonshot) MUST NOT traducirse.

| Scenario | G | W | Then |
|----------|---|---|------|
| Reasoning es | Locale `es` | Reasoning box muestra | "Pensando…" y "Pensó por X segundos" |
| Message-actions es | Locale `es` | Upvote/copy dispara | Toasts/tooltips en español |
| Provider sin traducción | Modelo Mistral | Selector lista modelos | Nombre "Mistral" se muestra sin traducción |
| Placeholder selector | Locale `es` | Selector abre | Placeholder "Buscar modelos..." u homólogo |

### Requirement: Contenido de páginas es

Páginas (settings/billing, profiles, workspaces, analytics overview/llm-gateway, agent-sessions, remote-browser, chat/[id]) MUST mostrar copy 100% en español.

| Scenario | G | W | Then |
|----------|---|---|------|
| Analytics es | Locale `es` | /analytics/overview renderiza | Copy de overview y llm-gateway en español |
| Remote-browser es | Locale `es` | remote-browser renderiza | Copy de la página en español |

### Requirement: Constants y E2E es

`lib/constants.ts` `suggestions[]` MUST estar en español. `tests/e2e/auth.test.ts` y `tests/e2e/model-selector.test.ts` SHOULD actualizar sus aserciones a texto en español (chat.test.ts es inmune por data-testid).

| Scenario | G | W | Then |
|----------|---|---|------|
| Suggestions es | Constants inicializan | Panel `es` renderiza | `suggestions[]` muestran opciones en español |
| E2E es | auth.test.ts con locale `es` | Suite e2e corre | Aserciones pasan contra texto español |

## Out of Scope

Contenido IA (prompt), contenido DB, next-intl, rediseño visual.