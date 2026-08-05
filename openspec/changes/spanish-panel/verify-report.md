# Verify Report: Spanish Panel

| Field | Value |
|-------|-------|
| Change | `spanish-panel` |
| Status | **IN PROGRESS** — static verification passed; E2E pending user execution |
| Artifact store | openspec |
| Delivery | single-pr-exception |

## Summary

The apply phase is complete and passed a fresh-context re-review (SSD gatekeeper + manual
grep for leftover English strings). All WARNING items from the prior review were resolved:

- `components/chat/toolbar.tsx` — `Fix error` now `t.panel.chat.toolbar.fixError`
  (`createFixErrorTool` accepts the label; `PureToolbar` consumes `useLanguage`).
- `components/chat/artifact-actions.tsx` — `Failed to execute action` →
  `t.panel.chat.artifactActions.failedToExecute`.
- `components/chat/messages.tsx` — `Scroll to bottom` → `t.panel.chat.messages.scrollToBottom`.
- `components/chat/version-footer.tsx` — `of` → `t.panel.chat.branch.of`, `Show changes`
  → `t.panel.chat.versionFooter.showChanges`.

Both `en`/`es` dictionary trees define every key consumed by the UI (verified in
`lib/i18n/index.tsx`, lines 508–525 EN and 1202–1219 ES).

## Static verification results

- All translated components resolve `t` from `useLanguage` (not hardcoded English).
- `es` is the default locale; `en`/`es` keys in parity.
- Consent-unrelated AI content and proprietary provider names (IDC, Mistral, DeepSeek,
  Moonshot) intentionally NOT translated (spec out of scope).
- Diff size within session budget: 1,365 insertions / 454 deletions across 43 files.

## Not executed by agent (user constraint: no bash for build/test/git)

The following require the user to run in their own terminal:

| Id | Check | Command | Status |
|----|-------|---------|--------|
| 6.1 | E2E auth/model-selector green | `pnpm test` | Pending |
| 6.2 | No-flash, default `es` cookie loads panel | manual or `pnpm test` routing | Pending |
| 6.3 | Toggle EN/ES persists cookie + localStorage, updates `html lang` + metadata | manual | Pending |
| 6.4 | Landing regression + provider backward-compat | `pnpm test` + manual | Pending |

## Risks

- User must run `pnpm test` to close Phase 6 and proceed to `archive`.
- If any E2E copy assertion drifts from the `es` dictionary values, the value (not the
  mechanism) must be corrected in `lib/i18n/index.tsx`.