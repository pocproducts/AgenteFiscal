# Follow-ups — session-telemetry-fixes (post-archive)

Status: OPEN. Base branch: `followups/session-telemetry-fixes` (from `feature/telemetry-ui-fixes`).
Original change: `session-telemetry-fixes` — archived 2026-08-19 (all 22 tasks complete, verify `pass_with_warnings`).
Evidence source: `openspec/changes/archive/2026-08-19-session-telemetry-fixes/verify-report.md`.

---

## 1. AST-4 — cost_cents deviation (spec amendment vs clamp to 0)

**Type**: decision (WARNING-1 in verify report)

**What the spec/design say**: `AST-4` and `design.md` require `cost_cents = 0` on persisted agent-session rows; the proposal explicitly lists non-zero cost as **out of scope**.

**What the code does**: `backend/agente_fiscal/api/routes/chat.py:1749` writes the real provider `cost_cents` for **browserbase** runs when the metrics payload carries it (`_last_metrics['cost_cents']`). Engine rows always write 0; composio/mock rows write 0. The behavior is best-effort and matches "telemetry never breaks the stream".

**Impact**: rows produced by browserbase runs can carry a real cost while the spec/design contract says 0. Not a crash, not a stream breaker; a contract literal mismatch.

**Open decision (needs the user)**:
- **Option A — amend the spec**: accept real cost as the intended behavior; update `specs/agent-session-telemetry/spec.md` AST-4 (and design ADR) so `cost_cents` reflects provider cost when available, default 0. Arguably better data (true cost in the sessions dashboard).
- **Option B — clamp to 0**: change `chat.py:1749` so browserbase rows also write 0, matching the current spec literal.

**Files involved**:
- `backend/agente_fiscal/api/routes/chat.py:1749`
- `openspec/specs/agent-session-telemetry/spec.md` (AST-4)
- `openspec/changes/archive/2026-08-19-session-telemetry-fixes/design.md`

---

## 2. Pre-existing backend suite failures (`report_runs.profile_id NOT NULL`)

**Type**: remediation (WARNING-2 in verify report) — scheduled for its own SDD change AFTER manual E2E testing of `feature/telemetry-ui-fixes` is complete.

**Scope**: 44 failures in the FULL backend suite (`pytest` collecting all of `agente_fiscal/tests/`), exit 1. **Zero overlap** with `session-telemetry-fixes` — NOT a regression from that change. All change-scoped suites are green (pytest 30/30 focused; vitest 66/66; theme e2e 3 passed/3 skipped-by-idiom).

**Breakdown by file**:
- `test_report_approval`: 17 failed
- `test_report_runs_api`: 13 failed
- `test_report_runner`: 12 failed
- `test_features`: 1 failed
- `test_clients_api`: 1 failed

**Root cause (verified)**: schema/model drift — `report_runs.profile_id` is `NOT NULL` in the DB schema, while the tests insert rows with `profile_id = NULL`. The model/schema expects a profile at write time; the test fixtures predate the constraint (or the constraint was added without updating fixtures).

**Verification evidence to reproduce**:
```bash
# from backend/
.venv/bin/pytest -q --no-cov          # full repo suite → expect 296 passed, 44 failed, exit 1
```

**Likely remediation paths (to detail in the new SDD proposal)**:
1. Audit the migration that introduced `report_runs.profile_id NOT NULL` and the current model.
2. Decide per test intent: fix fixtures to insert a real profile, or relax the constraint where NULL is legitimate (approval flow states).
3. Keep `test_report_approval`, `test_report_runs_api`, `test_report_runner` green together (they share the drift).

**Files involved (expected touched by the new SDD)**:
- Backend tests under `backend/agente_fiscal/tests/` (`test_report_approval.py`, `test_report_runs_api.py`, `test_report_runner.py`, `test_features.py`, `test_clients_api.py`)
- `report_runs` schema/model/migration (alembic)
- Possibly `ReportRun` model + repo

---

## Next steps

1. Complete manual E2E on `feature/telemetry-ui-fixes` (currently running locally: frontend :3000, backend :8000, Redis :6379).
2. Decide follow-up 1 (AST-4: amend spec vs clamp) — either with the user directly or folded into the next SDD.
3. Open a new SDD change for follow-up 2 (44 pre-existing failures) and route it through proposal → specs → design → tasks → apply → verify → archive.