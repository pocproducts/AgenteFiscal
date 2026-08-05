# Proposal: Spanish Panel — toda la startup en español

## Intent

UI de `app/(chat)` y `app/(auth)` hardcodeada en inglés con mezcla parcial de español (greeting, sidebar, slash-commands, CUIT/ARCA). El i18n (`lib/i18n/index.tsx` — `LanguageProvider`/`useLanguage`, en/es, `localStorage optimus-lang`) cubre solo `app/(landing)`; auth y panel quedan fuera y `html lang="en"` es fijo. Objetivo: toda la startup en español.

## Scope

### In Scope
- Auth: login, register, auth-form.tsx, auth layout
- Panel layout: app-sidebar, sidebar-history, sidebar-user-nav, chat-header, visibility-selector, shell.tsx, submit-button, document.tsx, image-editor
- Chat/AI: message.tsx, tool.tsx, reasoning.tsx, message-actions.tsx, suggestion.tsx, prompt-input.tsx, multimodal-input.tsx, model-selector
- Páginas: settings/billing, profiles, workspaces, analytics (overview, llm-gateway), agent-sessions, remote-browser, chat/[id]
- `lib/constants.ts` suggestions[], `html lang` + metadata
- E2E: auth.test.ts, model-selector.test.ts (rompen)

### Out of Scope
- Contenido IA (prompt, no UI), contenido DB, next-intl, rediseño visual

## Capabilities

### New Capabilities
- `i18n-panel`: extensión de lib/i18n a auth+panel; provider en raíz, default `es`, toggle EN/ES, manejo SSR
- `panel-ui-es`: strings de auth, layout, chat/AI, settings/analytics vía diccionario

### Modified Capabilities
- None (`openspec/specs/` vacío)

## Approach

- **Estrategia**: EXTENDER `lib/i18n` a auth+panel manteniendo toggle EN/ES global, default `es` (consistente con landing y `optimus-lang`). Descartada: español hardcode fijo (rompe switch existente).
- **SSR**: provider es cliente; design resuelve: (a) provider en raíz del panel, (b) strings server-side con locale por cookie/header, (c) híbrido. `html lang` + metadata del locale.
- **Entrega**: PRs encadenados (auth → layout → páginas → AI-elements). Session budget 2000 líneas; chaining en sdd-tasks.

## Affected Areas

| Area | Impact | Desc |
|------|--------|------|
| `lib/i18n/index.tsx` | Modified | Diccionario, default, scope panel |
| `app/layout.tsx` | Modified | lang dinámico + metadata |
| `app/(auth)/*`, `app/(chat)/**` | Modified | Strings → diccionario |
| `lib/constants.ts` | Modified | suggestions → es |
| `e2e/auth.test.ts`, `e2e/model-selector.test.ts` | Modified | Aserciones → es |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| E2E rompen | High | Tests en mismo PR |
| SSR/client mismatch | Med | Decidir en design |
| Volumen ~35 files | High | Chained PRs, 400/PR |
| Regresión landing | Low | Toggle + diff acotado |

## Rollback Plan

- Cada PR revierte individual (`git revert` del slice).
- Default `es` reversible vía flag; `optimus-lang` intacto.

## Decision Gap + Dependencies

1. ¿Toggle EN/ES global (recomendado) o español fijo? → toggle, default `es`.
2. ¿Default `es` para usuarios nuevos? → sí.
3. ¿Contenido IA fuera de alcance? → sí (prompt, no UI).

## Success Criteria

- [ ] 100% strings UI de auth+panel vía diccionario, sin hardcode nuevo
- [ ] Toggle EN/ES funciona y persiste en `optimus-lang`
- [ ] `html lang` + metadata correctos por locale
- [ ] `pnpm test` verde (E2E actualizados)
- [ ] Sin regresión en landing
