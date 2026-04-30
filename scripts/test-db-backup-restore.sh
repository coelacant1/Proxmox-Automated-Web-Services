#!/usr/bin/env bash
# PAWS DB backup/restore smoke test.
#
# Requires a running PostgreSQL instance (e.g. docker-compose up db).
# Tests the full backup -> drop -> restore cycle and verifies row counts match.
#
# Usage:
#   ./scripts/test-db-backup-restore.sh
#
# Set PAWS_DATABASE_URL to override the default connection.
# Exit codes: 0 = passed, 1 = failed

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

DB_URL="${PAWS_DATABASE_URL:-postgresql+asyncpg://paws:paws@localhost:5432/paws}"
DB_URL="${DB_URL/postgresql+asyncpg/postgresql}"

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

export PGPASSWORD="${DB_PASS}"

red()   { printf "\033[1;31m%s\033[0m\n" "$*" >&2; }
green() { printf "\033[1;32m%s\033[0m\n" "$*"; }
info()  { printf "[smoke] %s\n" "$*"; }

PSQL=(psql --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" --dbname="${DB_NAME}" --no-password --tuples-only --no-align --quiet)

# ---------------------------------------------------------------------------
# 1. Verify DB is reachable
# ---------------------------------------------------------------------------
info "Connecting to ${DB_HOST}:${DB_PORT}/${DB_NAME}..."
if ! psql --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" \
          --dbname="${DB_NAME}" --no-password -c "SELECT 1;" &>/dev/null; then
    red "ERROR: Cannot connect to database. Is docker-compose up?"
    exit 1
fi
green "Connection OK."

# ---------------------------------------------------------------------------
# 2. Count rows before backup
# ---------------------------------------------------------------------------
info "Counting rows in key tables before backup..."
USERS_BEFORE="$("${PSQL[@]}" -c "SELECT COUNT(*) FROM users;" 2>/dev/null | tr -d ' ' || echo 0)"
RESOURCES_BEFORE="$("${PSQL[@]}" -c "SELECT COUNT(*) FROM resources;" 2>/dev/null | tr -d ' ' || echo 0)"
info "  users:     ${USERS_BEFORE}"
info "  resources: ${RESOURCES_BEFORE}"

# ---------------------------------------------------------------------------
# 3. Backup
# ---------------------------------------------------------------------------
BACKUP_DIR="$(mktemp -d)"
trap 'rm -rf "${BACKUP_DIR}"' EXIT

info "Running backup-db.sh -> ${BACKUP_DIR}..."
PAWS_DATABASE_URL="${PAWS_DATABASE_URL:-postgresql://paws:paws@localhost:5432/paws}" \
    bash "${REPO_ROOT}/scripts/backup-db.sh" "${BACKUP_DIR}"

BACKUP_FILE="$(ls "${BACKUP_DIR}"/paws-db-*.sql.gz | head -1)"
if [[ -z "${BACKUP_FILE}" ]]; then
    red "ERROR: No backup file produced."
    exit 1
fi
green "Backup produced: $(basename "${BACKUP_FILE}")"

# ---------------------------------------------------------------------------
# 4. Drop all tables (simulate data loss without dropping the DB)
# ---------------------------------------------------------------------------
info "Dropping all tables to simulate data loss..."
PSQL_QUIET=(psql --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" --dbname="${DB_NAME}" --no-password --quiet)
"${PSQL_QUIET[@]}" -c "
DO \$\$ DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END \$\$;
"
TABLES_AFTER_DROP="$("${PSQL_QUIET[@]}" --tuples-only --no-align -c \
    "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public';" 2>/dev/null | tr -d ' ' || echo 0)"
info "Tables remaining after drop: ${TABLES_AFTER_DROP}"
if [[ "${TABLES_AFTER_DROP}" -ne 0 ]]; then
    red "ERROR: Tables still exist after drop. Cannot validate restore."
    exit 1
fi

# ---------------------------------------------------------------------------
# 5. Restore via restore-db.sh (non-interactive: pipe 'yes')
# ---------------------------------------------------------------------------
info "Running restore-db.sh with backup ${BACKUP_FILE}..."
echo "yes" | PAWS_DATABASE_URL="${PAWS_DATABASE_URL:-postgresql://paws:paws@localhost:5432/paws}" \
    bash "${REPO_ROOT}/scripts/restore-db.sh" "${BACKUP_FILE}"

# ---------------------------------------------------------------------------
# 6. Verify row counts match
# ---------------------------------------------------------------------------
info "Verifying row counts after restore..."
USERS_AFTER="$("${PSQL[@]}" -c "SELECT COUNT(*) FROM users;" 2>/dev/null | tr -d ' ' || echo -1)"
RESOURCES_AFTER="$("${PSQL[@]}" -c "SELECT COUNT(*) FROM resources;" 2>/dev/null | tr -d ' ' || echo -1)"
info "  users:     ${USERS_AFTER} (expected ${USERS_BEFORE})"
info "  resources: ${RESOURCES_AFTER} (expected ${RESOURCES_BEFORE})"

FAIL=0
if [[ "${USERS_AFTER}" != "${USERS_BEFORE}" ]]; then
    red "FAIL: users row count mismatch (${USERS_BEFORE} -> ${USERS_AFTER})"
    FAIL=1
fi
if [[ "${RESOURCES_AFTER}" != "${RESOURCES_BEFORE}" ]]; then
    red "FAIL: resources row count mismatch (${RESOURCES_BEFORE} -> ${RESOURCES_AFTER})"
    FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
    green "Smoke test passed: backup/restore cycle verified."
    exit 0
else
    exit 1
fi
