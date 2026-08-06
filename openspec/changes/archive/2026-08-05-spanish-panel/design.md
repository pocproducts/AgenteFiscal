# Design: Spanish Panel - toda la startup en espanol

## Technical Approach

Extend `lib/i18n/index.tsx` (LanguageProvider / useLanguage, `en`/`es`, localStorage
`optimus-lang`) so it covers auth and the authenticated panel, not only the landing
route. The provider becomes a client boundary wrapping all routes from the root
layout. The locale used on the server (html `lang`, metadata, server-rendered
strings) comes from a cookie named `optimus-lang`, synchronized with localStorage.
Default locale is `es`.

## Architecture Decisions

| ID | Decision | Choice | Rejected | Rationale |
|----|----------|--------|----------|-----------|
| D1 | Provider placement | Wrap `children` in root `app/layout.tsx` with a client boundary | Keep provider inside landing page | One source of locale state across landing, auth and chat; server can seed the initial locale. |
| D2 | SSR locale source | Cookie `optimus-lang` read via `cookies()` | localStorage or navigator only | localStorage is client-only, invisible to Server Components. A cookie is readable on the server, giving a correct first paint with no flash. |
| D3 | Client/server sync | Toggle writes cookie (server action) and localStorage. Provider receives `initialLocale` from the server and syncs a legacy localStorage value once on hydration | Cookie only / localStorage only | Cookie enables SSR correctness; localStorage keeps the existing landing persistence contract (`optimus-lang`). |
| D4 | Default locale | `es` | `en` | Spec and proposal: Spanish-first. Users who previously stored `optimus-lang=en` keep English via the hydration sync. |
| D5 | Auth errors | Keep typed status codes; map code to dictionary string in the client | Return UI strings from actions | Server actions have no locale context. Codes keep type-safety; the client owns translation. |

## SSR handling (no flash, no double-render)

- Root layout reads the `optimus-lang` cookie (validated to `es` or `en`, default
  `es`), sets `html lang` accordingly and exposes the locale to `generateMetadata`.
  First paint is already in the right language.
- `app/(chat)/layout.tsx` already awaits `cookies()`; it reuses the same cookie for
  any server-rendered panel strings (agent sidebar labels, etc.).
- The provider gets `initialLocale` from the server and initializes state with it
  instead of defaulting to `en` inside a `useEffect` (the current flash source).
- A one-time hydration effect reads `localStorage optimus-lang` and, if it differs
  from the cookie (legacy landing visitors who chose `en` before the cookie layer),
  syncs both. This is a rare single sync, not a double render.

## Data Flow

```
Landing toggle -> setLanguage(lang)
   -> document.documentElement.lang = lang
   -> localStorage.setItem("optimus-lang", lang)
   -> server action writes optimus-lang cookie

Root server layout -> cookies() -> locale (default es)
   -> html lang={locale}, generateMetadata({ title, description })
   -> <LanguageProvider initialLocale={locale}> wraps children

Client components -> useLanguage() -> { language, setLanguage, t }
Server components -> getDictionary(locale) (new server helper, no hook)
```

## Dictionary and Constants

- Keep the existing `translations` object (`en` and `es` trees, `as const`, cast to
  `Translations["en"]`).
- Add namespaces to both trees, keyed by zone:
  - `auth.*` (login/register headings, back link, poweredBy, signIn/signUp,
    error toasts, submit loading).
  - `panel.sidebar.*` (newReport, history groups, nav items, tooltips, user menu,
    confirm dialog).
  - `panel.chat.*` (reasoning "Thinking...", message actions, tool, prompt input
    placeholders, model selector placeholder).
  - `panel.pages.*` (settings, profiles, workspaces, analytics, agent-sessions,
    remote-browser).
- Strings already in Spanish (CUIT/ARCA, "Rentas Cordoba - IIBB", "Nuevo Informe",
  suggestion labels) become the `es` values of their keys; add the `en` counterpart.
  They are captured once in the dictionary, not re-translated during apply.
- `lib/constants.ts` suggestions move to the dictionary or become locale-aware;
  the panel reads them through `useLanguage`.

## Auth Toasts (server-side validation)

`LoginActionState` and `RegisterActionState` already return status codes
(`failed`, `invalid_data`, `user_exists`, `success`). Keep that contract. The login
and register pages map each status to `t.auth.errors.<code>` inside their existing
`useEffect` toast callbacks. Zod field errors get per-field dictionary keys if
needed. No server-side string changes required.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| E2E | `auth.test.ts` | Seed `optimus-lang=es` cookie (or rely on default) and assert Spanish copy (e.g. "Welcome back", "Create account", error toasts). |
| E2E | `model-selector.test.ts` | Assert Spanish placeholder ("Buscar modelos..." or equivalent) for the `es` locale. |
| E2E | `chat.test.ts` | Unchanged: assertions use `data-testid`, immune to copy changes. |

## Migration and Rollout

No database migration. Default changes from `en` to `es`; users who explicitly chose
`en` keep it via cookie/localStorage sync. Deliverable in chained PRs per the
proposal (auth, layout, pages, AI elements); each slice reverts individually.

## Open Questions

- Where to put the cookie-writing server action (server action vs route handler)
  respecting `NEXT_PUBLIC_BASE_PATH`; decided during apply.
- Confirm whether `html lang` should also update for legacy localStorage-only users
  on their first panel visit (accepted: one-time sync).
- Keep "Powered by / AI Gateway" brand copy in English or translate: pending product
  decision, default keep brand as-is.
