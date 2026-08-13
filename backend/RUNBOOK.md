# Agente Fiscal — Backend Runbook

Operational runbook for the FastAPI backend: backup/restore, risk diagnostics,
staging bootstrap, and the prerequisites the external integrations need.

Everything is configured ONLY through environment variables / `.env`; no secret
is stored in the repository.

---

## 1. Worker reliability (the SKIP LOCKED claim)

The in-process worker (`agente_fiscal/worker/runner.py`) polls `report_runs`
rows with `status='queued'` and runs the fiscal pipeline for each one. The
Dockerfile launches uvicorn with `--workers 2`, i.e. **two uvicorn processes,
each running its own worker loop against the same database**.

`ReportRunner.claim_next_queued()` claims a row **atomically**:

```
SELECT ... FROM report_runs
WHERE status = 'queued'
ORDER BY created_at, id
LIMIT 1
FOR UPDATE SKIP LOCKED
```

and flips `queued -> running` in the **same transaction** before committing.
Because the row lock is held from SELECT time until commit, a competing worker
can never see the same row — the `FOR UPDATE` blocks it, `SKIP LOCKED` makes it
skip ahead to the next run instead of waiting. Two workers on one database are
now **safe**: each queued run is claimed exactly once.

Consequences:

- Oldest-first dispatch is preserved (`ORDER BY created_at, id` inside the
  locking query).
- After a crash between claim and pipeline execution the row is left in
  `running` (not `queued`), so it is not retried automatically. To force a
  retry, `UPDATE report_runs SET status='queued' WHERE id = '<id>'`.
- Staging should still use its **own database** (see §4) so a staging worker
  never competes with the production worker.

---

## 2. Backup

`backend/scripts/backup.sh` uses `pg_dump` (custom format `-Fc`) against
`DATABASE_URL_UNPOOLED` (falls back to `DATABASE_URL`). No database is
contacted until the script runs.

```bash
export DATABASE_URL_UNPOOLED='postgresql://user:pass@host:5432/db?sslmode=require'
cd backend
./scripts/backup.sh
```

- Writes `backend/artifacts/backups/agente_fiscal_<YYYYmmdd_HHMMSS>.dump`
  (directory overridable with `BACKUP_DIR`) plus a `latest.dump` symlink.
- Exits non-zero with a clear message on missing URL, missing `pg_dump`, or a
  failed dump (invalid dumps are deleted).
- `./scripts/backup.sh --help` prints usage without touching the network.

Automate it with a cron/systemd timer:

```cron
30 1 * * * cd /srv/agente-fiscal/backend && \
  /usr/bin/env DATABASE_URL_UNPOOLED='...' ./scripts/backup.sh >> /var/log/agente-backup.log 2>&1
```

---

## 3. Restore

`backend/scripts/restore.sh` restores the latest dump (or a given one) into a
target database using `pg_restore --clean --if-exists`.

**It requires `TARGET_DATABASE_URL` explicitly** — it never guesses a target,
so production cannot be clobbered by a stray invocation. It also asks you to
type `RESTORE` unless `FORCE=1` is set.

```bash
export TARGET_DATABASE_URL='postgresql://user:pass@host:5432/db?sslmode=require'
cd backend
./scripts/restore.sh                # restores artifacts/backups/latest.dump
./scripts/restore.sh /path/to/agente_fiscal_20260813_0200.dump
```

Headless:

```bash
FORCE=1 ./scripts/restore.sh /path/to/dump.dump
```

> Restoring onto a live pooler target uses `pg_restore --clean`, which drops
> and recreates objects — run it against a dedicated database, never the
> production pooler while production is writing.

### Restore-to-staging example

```bash
# 1. Create the staging database (own Postgres or same cluster, different name)
createdb "$STAGING_DATABASE_URL"        # or: psql postgres -c 'CREATE DATABASE agente_staging'

# 2. Restore the latest dump into it
export TARGET_DATABASE_URL="$STAGING_DATABASE_URL"
./scripts/restore.sh /path/to/latest.dump
```

---

## 4. Staging setup (mínimo)

Staging runs the same code with **separate environment variables**. Because
`agente_fiscal/db/session.py` builds its async engine from `DATABASE_URL` at
import time, each instance must be its own process with its own env.

```bash
cd backend
export DATABASE_URL='postgresql://user:pass@staging-host:5432/agente_staging_pooled?sslmode=require'
export DATABASE_URL_UNPOOLED='postgresql://user:pass@staging-host:5432/agente_staging?sslmode=require'
export REDIS_URL='redis://localhost:6379/1'     # staging DB index, NOT 0
export CORS_ORIGINS='http://localhost:3001'
export APP_ENV='staging'

# Schema from migrations (never copy Prod schema into a fresh staging DB
# unless you WANT prod's data — see restore-to-staging above):
alembic upgrade head

# Run on its own port:
uvicorn agente_fiscal.api.server:app --port 8001 --workers 2
```

Rules of thumb:

| Resource        | Production            | Staging                         |
|-----------------|-----------------------|---------------------------------|
| Database        | `DATABASE_URL` / `DATABASE_URL_UNPOOLED` of the Neon prod DB | **Own** `*_staging` DB and unpooled URL (separate names) |
| Redis           | `REDIS_URL=.../0`     | Own `REDIS_URL=.../N` (different DB index or host) |
| Port            | 8000                  | 8001 (or any free port)         |
| Certs+keys      | `.certificados-arca/` | Staging's own dir via `CERT_DIR` |

Two instances can coexist on the same host as long as URLs (DB, unpooled DB,
Redis) and the `--port` all differ. The worker races on shared rows are now
resolved by the SKIP LOCKED claim (§1), so even a shared DB is safe — but
staging should still use its own database to keep staging runs (with staging
certificates and Composio keys) out of production data.

---

## 5. ARCA certificates and Composio prerequisites

### Certificates

Paths are resolved from the `CERT_DIR` setting:

- Env key: `CERT_DIR` (default `.certificados-arca`, relative to the process
  CWD — existing deployments keep working unchanged).
- Resolved files (exported from `agente_fiscal.config`):
  - `CERT_PATH = <CERT_DIR>/produccion.crt`
  - `KEY_PATH  = <CERT_DIR>/produccion.key`

```bash
export CERT_DIR=/srv/agente-fiscal/.certificados-arca   # optional; default is local dir
ls "$CERT_DIR/produccion.crt" "$CERT_DIR/produccion.key"
```

`GET /v1/health` reports the `ta` service as `down` with the **exact resolved
paths** of the missing certificate files, so ops knows where to drop them.
Both `.certificados-arca/` and `storage/` are gitignored at repo root and under
`backend/`.

### Composio (browser automation)

- Env key: `COMPOSIO_API_KEY` (empty default). Read by `config.py` and used in
  the report worker, extract/report/chat routes, the CLI, the MCP server, and
  `browser/composio.py`.
- Gated behind `BROWSER_ENABLED` (default `false`). When disabled, the health
  check reports `disabled` and the integrations return a clean
  `INTEGRATION_DISABLED` instead of touching the cloud.

### Enrollment flags

| Integration | Env key      | Default |
|-------------|--------------|---------|
| ARCA/WSAA   | `ARCA_ENABLED`  | `false` |
| Composio    | `BROWSER_ENABLED` | `false` |
| PDF         | `PDF_ENABLED` | `true`  |

`MEMORY_ENABLED` (default `true`) governs the Engram memory client.

---

## 6. Common diagnostics

- Check health: `curl -s localhost:8000/v1/health | python3 -m json.tool`
  - `ta: down` + missing file paths → drop certs at the reported paths (§5).
  - `composio: down` → set `COMPOSIO_API_KEY` (or accept it's disabled).
  - `postgres: down` → `DATABASE_URL`/`DATABASE_URL_UNPOOLED` wrong or unreachable.
- A run stuck in `running`: crash after claim (§1) — flip it back to `queued`
  to retry.
- Migrations use `DATABASE_URL_UNPOOLED` only (transaction poolers break the
  prepared-statement protocol); the app engine uses the pooled `DATABASE_URL`.