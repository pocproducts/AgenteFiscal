#!/usr/bin/env bash
# Backup the Agente Fiscal PostgreSQL database with pg_dump.
#
# Configuration comes ONLY from the environment — no secrets live in this repo:
#
#   DATABASE_URL_UNPOOLED   Direct (non-pooled) connection URL. Preferred
#                           because it mirrors what Alembic uses and avoids
#                           transaction-pooler quirks.
#   DATABASE_URL            Fallback when the unpooled URL is not set.
#   BACKUP_DIR              Where dumps land. Default: backend/artifacts/backups
#
# Writes a timestamped custom-format dump (pg_restore -Fc compatible) and a
# `latest.dump` symlink for restore.sh. Exits non-zero on any failure.
set -euo pipefail

BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${BACKEND_ROOT}/artifacts/backups}"

# Prefer the unpooled URL (Alembic-grade, direct); fall back to the pooled one.
if [[ -n "${DATABASE_URL_UNPOOLED:-}" ]]; then
	DB_URL="${DATABASE_URL_UNPOOLED}"
else
	DB_URL="${DATABASE_URL:-}"
fi

usage() {
	cat <<'EOF'
Back up the Agente Fiscal PostgreSQL database.

Usage: backup.sh [--help]

Environment:
  DATABASE_URL_UNPOOLED   Direct (non-pooled) connection URL (required; falls back to DATABASE_URL).
  DATABASE_URL            Fallback pooled URL when the unpooled one is unset.
  BACKUP_DIR              Where dumps are written. Default: backend/artifacts/backups

Output: <BACKUP_DIR>/agente_fiscal_<timestamp>.dump plus a latest.dump symlink.
EOF
}

# Return a connection URL with its password masked for operator-safe output.
mask_url() {
	local url="$1"
	# user:pass@  ->  user:***@  (also handles user:@ trailing-colon edge)
	url="${url/:\/\/[^:@/]*:[^@/]*@/:\/\/***:***@}"
	printf '%s' "$url"
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
	usage
	exit 0
fi

if [[ -z "$DB_URL" ]]; then
	echo "ERROR: DATABASE_URL_UNPOOLED (or DATABASE_URL) is not set — refusing to back up against an unknown database." >&2
	exit 1
fi
if ! command -v pg_dump >/dev/null 2>&1; then
	echo "ERROR: pg_dump not found on PATH. Install PostgreSQL client tools first." >&2
	exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_FILE="${BACKUP_DIR}/agente_fiscal_${STAMP}.dump"

echo "→ Dumping $(mask_url "$DB_URL") ..."
if ! pg_dump -d "$DB_URL" -Fc -v -f "$DUMP_FILE" 1>&2; then
	rm -f "$DUMP_FILE"
	echo "ERROR: pg_dump failed — no backup written." >&2
	exit 1
fi

ln -sf "$(basename "$DUMP_FILE")" "${BACKUP_DIR}/latest.dump"
echo "✓ Backup written: $DUMP_FILE"
echo "  latest.dump → $(basename "$DUMP_FILE")"