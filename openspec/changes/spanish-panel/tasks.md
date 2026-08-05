# Tasks: Spanish Panel — toda la startup en español

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,800 (session budget: 2,000) |
| 400-line budget risk | Overridden |
| Chained PRs recommended | No (user chose single PR) |
| Suggested split | Single PR with `size:exception` |
| Delivery strategy | single-pr-exception |
| Chain strategy | N/A (single PR) |

```text
Decision needed before apply: No
Chained PRs recommended: No (single PR, size exception approved by user)
400-line budget risk: Overridden (session budget 2,000, estimated ~1,800)
```

`single-pr-exception`: all changes delivered in ONE PR (~1,800 lines, within the 2,000-line session budget). The work-unit groups below are apply-progress phases, not separate PRs.

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Infra (dictionary, provider, cookie/SSR) + auth | PR #1 | Base to main. Dictionary (~250 lines) is the single biggest diff; keep it here so later PRs only consume keys. Includes E2E auth. |
| 2 | Panel layout components | PR #2 | Depends on PR #1; lands `suggestions` via dictionary. |
| 3 | Pages (settings, analytics, agent-sessions, remote-browser, chat/[id]) | PR #3 | Depends on PR #2. |
| 4 | AI elements + E2E model-selector | PR #4 | Depends on PR #1 dictionary; small surface. |

## Phase 1 — Infra: dictionary, provider, cookie/SSR (group `auth`)

- [x] 1.1 `lib/i18n/index.tsx` — add namespaces to both `en`/`es` trees: `auth.*` (headings, back, poweredBy, signIn/signUp, error toasts, submit loading), `panel.sidebar.*` (newReport, history labels/groups, nav items, tooltips, user menu, confirm dialog), `panel.chat.*` (reasoning, message actions, tool, prompt placeholders, model-selector placeholder), `panel.pages.*` (settings, analytics, agent-sessions, remote-browser). Already-Spanish strings (CUIT/ARCA, "Rentas Córdoba — IIBB", "Nuevo Informe", suggestion labels) become `es` values; add `en` counterparts.
- [x] 1.2 `lib/i18n/index.tsx` — `LanguageProvider` accepts `initialLocale` prop (default `es`), seeds state from it (no `useEffect` default flash), one-time hydration sync: read legacy `localStorage optimus-lang`, if different from cookie write both.
- [x] 1.3 `app/layout.tsx` — read `optimus-lang` cookie via `cookies()`, validate `es|en`, default `es`; set dynamic `html lang`, `generateMetadata` title/description per locale; wrap children with `LanguageProvider initialLocale={locale}` inside existing providers.
- [x] 1.4 New `lib/i18n/server.ts` (or `lib/i18n/get-dictionary.ts`) — server-side `getDictionary(locale)` helper (no hook) for server-rendered panel strings.
- [x] 1.5 New cookie server action/handler — `setLocale(lang)` writes `optimus-lang` cookie (respect `NEXT_PUBLIC_BASE_PATH`), called from client toggle after `setLanguage`.
- [x] 1.6 `app/(chat)/layout.tsx` — reuse cookie locale from `cookies()` (already awaited) for server-rendered strings (e.g. agent sidebar labels).

## Phase 2 — Auth copy (group `auth`, uses Phase 1 dictionary)

- [x] 2.1 `app/(auth)/login/page.tsx`, `register/page.tsx` — replace headings/subtitle/back-link copy with `t.auth.*`; map status codes (`failed`, `invalid_data`, `user_exists`, `success`) to `t.auth.errors.*` in existing toast `useEffect`; no server string changes.
- [x] 2.2 `components/chat/auth-form.tsx` — labels (Email/Password) and `user@acme.com` placeholder via `t.auth.*`.
- [x] 2.3 `app/(auth)/layout.tsx` — "Powered by / AI Gateway" brand copy: spec REQ 5 requires Spanish; resolve to `t.auth.poweredBy` with Spanish `es` value (brand decision resolved to spec), `es` default.
- [x] 2.4 `lib/constants.ts` — `suggestions[]` become locale-aware or move to dictionary (`panel.chat.suggestions`); panel reads via `useLanguage`.
- [x] 2.5 `tests/e2e/auth.test.ts` — assert Spanish copy (e.g. "Create account", "Sign in", error toasts) with default `es` locale; update placeholders/labels.

## Phase 3 — Panel layout (group `layout`)

- [x] 3.1 `components/chat/app-sidebar.tsx` — nav items, tooltips, "Nuevo Informe", Agent Sessions/Analytics/Settings groups via `t.panel.sidebar.*`.
- [x] 3.2 `components/chat/sidebar-history.tsx` — History label, Today/Yesterday/Last 7 days/Last 30 days/Older, empty/loading states, delete confirm dialog, "Chat deleted" toast via dictionary.
- [x] 3.3 `components/chat/sidebar-user-nav.tsx` — user menu items (settings, sign out, theme labels) via `t.panel.sidebar.*`.
- [x] 3.4 Chat shell components — `chat-header.tsx`, `shell.tsx`, `visibility-selector.tsx`, `submit-button.tsx` (loading state), `document.tsx`, `image-editor.tsx` strings via `t.panel.chat.*`.

## Phase 4 — Pages (group `pages`)

- [x] 4.1 `app/(chat)/settings/billing/page.tsx`, `settings/profiles/page.tsx`, `settings/workspaces/page.tsx` — copy via `t.panel.pages.settings.*`.
- [x] 4.2 `app/(chat)/analytics/overview/page.tsx`, `analytics/llm-gateway/page.tsx` — copy via `t.panel.pages.analytics.*` (spec scenario: overview + llm-gateway es).
- [x] 4.3 `app/(chat)/agent-sessions/page.tsx`, `remote-browser/page.tsx`, `chat/[id]/page.tsx` — copy via `t.panel.pages.*`.

## Phase 5 — AI elements + E2E (group `ai-elements`)

- [x] 5.1 `components/ai-elements/message.tsx`, `tool.tsx`, `suggestion.tsx` — UI strings via `t.panel.chat.*` (assistant message content NOT translated — spec out of scope).
- [x] 5.2 `components/ai-elements/reasoning.tsx` — default `getThinkingMessage` via `t.panel.chat.reasoning` ("Pensando…", "Pensó por X segundos"); keep `getThinkingMessage` prop API.
- [x] 5.3 `components/chat/message-actions.tsx` — upvote/copy tooltips and toasts via dictionary.
- [x] 5.4 `components/ai-elements/prompt-input.tsx` — placeholders ("What would you like to know?"), aria-labels ("Upload files", "Stop"/"Submit"), "Add photos or files", error messages via `t.panel.chat.*`.
- [x] 5.5 `components/ai-elements/model-selector.tsx` + consumer — placeholder "Search models..."/"Buscar modelos..." via `t.panel.chat.modelPlaceholder`; provider names (Mistral, DeepSeek, Moonshot) NOT translated.
- [x] 5.6 `tests/e2e/model-selector.test.ts` — assert Spanish placeholder for `es` locale (spec scenario).

## Phase 6 — Verification

- [ ] 6.1 Run `pnpm test` — E2E auth/model-selector green; `chat.test.ts` unchanged (data-testid immune).
- [ ] 6.2 Verify no-flash: panel route loads with stored `es` cookie without English flash or double render.
- [ ] 6.3 Verify toggle EN/ES persists `optimus-lang` cookie + localStorage and updates `html lang` + metadata.
- [ ] 6.4 Regression check: landing (`app/(landing)`) still works with toggle; provider move is backward compatible.
