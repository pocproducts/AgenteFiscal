#!/usr/bin/env bash
# Restore an Agente Fiscal PostgreSQL dump.
#
# Safety-first: this script NEVER restores against the production pooler by
# default — the target database MUST be given explicitly via TARGET_DATABASE_URL,
# and a confirmation prompt asks for "RESTORE" unless FORCE=1 is set.
#
# Environment:
#   TARGET_DATABASE_URL   The database to restore INTO (required).
#   BACKUP_DIR            Where dumps live (default: backend/artifacts/backups).
#   FORCE=1               Skip the interactive confirmation prompt.
#
# Usage:
#   restore.sh                       # restore ./artifacts/backups/latest.dump
#   restore.sh /path/to/dump.dump    # restore a specific dump
set -euo pipefail

BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${BACKEND_ROOT}/artifacts/backups}"
TARGET_DB="${TARGET_DATABASE_URL:-}"

usage() {
	cat <<'EOF'
Restore an Agente Fiscal PostgreSQL dump into a target database.

Usage: restore.sh [DUMP_FILE] [--help]

Environment:
  TARGET_DATABASE_URL   Required. The database to restore INTO (never defaults
                        to anything, so production can't be clobbered by accident).
  BACKUP_DIR            Where dumps live. Default: backend/artifacts/backups
  FORCE=1               Skip the interactive "RESTORE" confirmation.

The restore uses pg_restore --clean --if-exists, i.e. it REPLACES the schema
and data of the target database with the contents of the dump.
EOF
}

mask_url() {
	local url="$1"
	url="${url/:\/\/[^:@/]*:[^@/]*@/:\/\/***:***@}"
	printf '%s' "$url"
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
	usage
	exit 0
fi

if [[ -z "$TARGET_DB" ]]; then
	echo "ERROR: TARGET_DATABASE_URL must be set — refusing to guess where a dump should go." >&2
	echo "       Hint: staging uses its OWN database (its own DATABASE_URL / DATABASE_URL_UNPOOLED)." >&2
	exit 1
fi

DUMP="${1:-}"
if [[ -z "$DUMP" ]]; then
	DUMP="${BACKUP_DIR}/latest.dump"
fi
if [[ ! -f "$DUMP" ]]; then
	echo "ERROR: dump not found: $DUMP (run backup.sh first, or pass a path)." >&2
	exit 1
fi
if ! command -v pg_restore >/dev/null 2>&1; then
	echo "ERROR: pg_restore not found on PATH. Install PostgreSQL client tools first." >&2
	exit 1
fi

if [[ "${FORCE:-0}" != "1" ]]; then
	echo "You are about to REPLACE ALL DATA in: $(mask_url "$TARGET_DB")"
	echo "  with: $DUMP"
	read -r -p "Type RESTORE to continue: " REPLY
	if [[ "$REPLY" != "RESTORE" ]]; then
		echo "Aborted — nothing was touched." >&2
		exit 1
	fi
fi

if [[ "${FORCE:-0}" == "1" ]]; then
	echo "FORCE=1 — restoring WITHOUT confirmation into: $(mask_url "$TARGET_DB")"
fi

echo "→ Restoring $DUMP ..."
if ! pg_restore --clean --if-exists --no-owner --no-privileges -d "$TARGET_DB" "$DUMP" 1>&2; then
	echo "ERROR: pg_restore failed — target may be partially restored. Re-run to complete, or restore against a fresh DB." >&2
	exit 1
fi
echo "✓ Restore complete into $(mask_url "$TARGET_DB")"