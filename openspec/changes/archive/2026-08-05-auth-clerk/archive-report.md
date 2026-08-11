# Archive Report — auth-clerk

**Archived at**: 2026-08-05
**Mode**: Automatic · OpenSpec
**Archive path**: `openspec/changes/archive/2026-08-05-auth-clerk/`
**Closure type**: CANCELLED / OBSOLETE

## Summary

This change proposed replacing NextAuth v5 with Clerk behind a hexagonal AuthPort. It was a planning artifact only: proposal, spec, design, and tasks existed, but no implementation or verification was performed.

## Why Cancelled

- The repository was restructured into `frontend/` + `backend/` pnpm workspaces (commit `9e24df4`).
- NextAuth was removed outright in that restructure; no Clerk migration followed.
- The auth stack is being re-planned from scratch and this design no longer reflects the codebase.

## State at Archive

| Artifact | Status |
|----------|--------|
| change.yaml | updated → `cancelled-archived` |
| exploration.md | moved (planning only) |
| proposal.md | moved (planning only) |
| spec.md | moved (planning only) |
| design.md | moved (planning only) |
| tasks.md | moved (planning only) |
| verify-report.md | none (never implemented) |
| archive-report.md | ✅ (this file) |

## Notes

- No implementation, tests, or verification were performed for this change.
- The active `openspec/changes/auth-clerk/` directory was moved to archive.
