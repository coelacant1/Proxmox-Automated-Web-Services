#!/usr/bin/env bash
# PAWS database backup script.
#
# Reads connection details from PAWS_DATABASE_URL (same env var the app uses).
# Writes a gzip-compressed pg_dump to the target directory.
#
# Usage:
#   ./scripts/backup-db.sh [output_dir]
#
# Examples:
#   ./scripts/backup-db.sh                      # writes to ./backups/
#   ./scripts/backup-db.sh /mnt/nas/paws-backups
#   PAWS_DATABASE_URL=postgresql+asyncpg://u:p@host/db ./scripts/backup-db.sh
#
# The output filename is:  paws-db-YYYYMMDD-HHMMSS.sql.gz
# Exit codes: 0 = success, 1 = error

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default DB URL matches docker-compose default; override via env
DB_URL="${PAWS_DATABASE_URL:-postgresql+asyncpg://paws:paws@localhost:5432/paws}"

# Strip asyncpg dialect so psql/pg_dump accept the URL
DB_URL="${DB_URL/postgresql+asyncpg/postgresql}"

# Output directory (first arg or ./backups)
OUTPUT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)/backups}"

# ---------------------------------------------------------------------------
# Parse connection parameters from URL
# postgresql://user:password@host:port/dbname
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
# Remove any query string
DB_NAME="${DB_NAME%%\?*}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
red()   { printf "\033[1;31m%s\033[0m\n" "$*" >&2; }
green() { printf "\033[1;32m%s\033[0m\n" "$*"; }
info()  { printf "[backup] %s\n" "$*"; }

require_cmd() {
    if ! command -v "$1" &>/dev/null; then
        red "ERROR: '$1' not found. Install postgresql-client."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
require_cmd pg_dump
require_cmd gzip

mkdir -p "$OUTPUT_DIR"

TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
OUTFILE="${OUTPUT_DIR}/paws-db-${TIMESTAMP}.sql.gz"

info "Host:     ${DB_HOST}:${DB_PORT}"
info "Database: ${DB_NAME}"
info "User:     ${DB_USER}"
info "Output:   ${OUTFILE}"

# ---------------------------------------------------------------------------
# Dump
# ---------------------------------------------------------------------------
export PGPASSWORD="${DB_PASS}"

if pg_dump \
    --host="${DB_HOST}" \
    --port="${DB_PORT}" \
    --username="${DB_USER}" \
    --dbname="${DB_NAME}" \
    --format=plain \
    --no-owner \
    --no-acl \
    | gzip > "${OUTFILE}"; then
    SIZE="$(du -sh "${OUTFILE}" | cut -f1)"
    green "Backup complete: ${OUTFILE} (${SIZE})"
else
    red "ERROR: pg_dump failed."
    rm -f "${OUTFILE}"
    exit 1
fi
