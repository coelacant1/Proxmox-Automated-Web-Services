#!/usr/bin/env bash
# PAWS database restore script.
#
# Reads connection details from PAWS_DATABASE_URL (same env var the app uses).
# Accepts a gzip-compressed or plain SQL backup file produced by backup-db.sh.
#
# Usage:
#   ./scripts/restore-db.sh <backup_file>
#
# Examples:
#   ./scripts/restore-db.sh backups/paws-db-20260421-120000.sql.gz
#   ./scripts/restore-db.sh backups/paws-db-20260421-120000.sql
#
# WARNING: This will DROP all existing tables and restore from the backup.
#          Stop the PAWS app before running to avoid in-flight transactions.
#
# Exit codes: 0 = success, 1 = error

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_URL="${PAWS_DATABASE_URL:-postgresql+asyncpg://paws:paws@localhost:5432/paws}"
DB_URL="${DB_URL/postgresql+asyncpg/postgresql}"

# ---------------------------------------------------------------------------
# Parse connection parameters from URL
# ---------------------------------------------------------------------------
_strip_proto="${DB_URL#postgresql://}"
DB_USER="${_strip_proto%%:*}"
_after_user="${_strip_proto#*:}"
DB_PASS="${_after_user%%@*}"
_after_pass="${_after_user#*@}"
DB_HOST="${_after_pass%%:*}"
_after_host="${_after_pass#*:}"
DB_PORT="${_after_host%%/*}"
DB_NAME="${_after_host#*/}"
DB_NAME="${DB_NAME%%\?*}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
red()    { printf "\033[1;31m%s\033[0m\n" "$*" >&2; }
yellow() { printf "\033[1;33m%s\033[0m\n" "$*"; }
green()  { printf "\033[1;32m%s\033[0m\n" "$*"; }
info()   { printf "[restore] %s\n" "$*"; }

require_cmd() {
    if ! command -v "$1" &>/dev/null; then
        red "ERROR: '$1' not found. Install postgresql-client."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Argument check
# ---------------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
    red "Usage: $0 <backup_file>"
    red "  backup_file: path to .sql.gz or .sql backup produced by backup-db.sh"
    exit 1
fi

BACKUP_FILE="$1"

if [[ ! -f "${BACKUP_FILE}" ]]; then
    red "ERROR: Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
require_cmd psql
require_cmd pg_dump

if [[ "${BACKUP_FILE}" == *.gz ]]; then
    require_cmd gunzip
    COMPRESSED=true
else
    COMPRESSED=false
fi

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------
yellow "============================================================"
yellow " WARNING: This will replace ALL data in '${DB_NAME}'."
yellow " Host:     ${DB_HOST}:${DB_PORT}"
yellow " Database: ${DB_NAME}"
yellow " Backup:   ${BACKUP_FILE}"
yellow "============================================================"
printf "Type 'yes' to continue: "
read -r CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
    info "Aborted."
    exit 0
fi

export PGPASSWORD="${DB_PASS}"

PSQL_OPTS=(--host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" --dbname="${DB_NAME}" --no-password)
PSQL_ADMIN=(--host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" --dbname="postgres" --no-password)

# ---------------------------------------------------------------------------
# Drop existing schema and recreate
# ---------------------------------------------------------------------------
info "Terminating existing connections to ${DB_NAME}..."
psql "${PSQL_ADMIN[@]}" -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" \
    --quiet

info "Dropping and recreating database ${DB_NAME}..."
psql "${PSQL_ADMIN[@]}" -c "DROP DATABASE IF EXISTS \"${DB_NAME}\";" --quiet
psql "${PSQL_ADMIN[@]}" -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";" --quiet

# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
info "Restoring from ${BACKUP_FILE}..."

if $COMPRESSED; then
    gunzip --stdout "${BACKUP_FILE}" | psql "${PSQL_OPTS[@]}" --quiet
else
    psql "${PSQL_OPTS[@]}" --quiet < "${BACKUP_FILE}"
fi

green "Restore complete. Database '${DB_NAME}' is ready."
info "Run 'alembic upgrade head' if the backup pre-dates recent migrations."
