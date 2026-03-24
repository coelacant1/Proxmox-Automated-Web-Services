#!/usr/bin/env bash
# Run the same CI checks locally that GitHub Actions runs.
# Usage: ./scripts/ci-local.sh [--fix]
#   --fix  Auto-fix lint/format issues instead of just checking

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIX_MODE=false
FAILED=0

if [[ "${1:-}" == "--fix" ]]; then
    FIX_MODE=true
fi

red()   { printf "\033[1;31m%s\033[0m\n" "$*"; }
green() { printf "\033[1;32m%s\033[0m\n" "$*"; }
blue()  { printf "\033[1;34m%s\033[0m\n" "$*"; }

run_step() {
    local label="$1"
    shift
    blue "=== $label ==="
    if "$@"; then
        green "PASS: $label"
    else
        red "FAIL: $label"
        FAILED=$((FAILED + 1))
    fi
    echo
}

# --- Backend lint (matches: ruff check . && ruff format --check .) ---
cd "$REPO_ROOT/backend"

if $FIX_MODE; then
    run_step "backend-lint: ruff check (auto-fix)" python -m ruff check --fix .
    run_step "backend-lint: ruff format (auto-fix)" python -m ruff format .
else
    run_step "backend-lint: ruff check" python -m ruff check .
    run_step "backend-lint: ruff format --check" python -m ruff format --check .
fi

# --- Backend test (matches: pytest --cov=app) ---
run_step "backend-test: pytest" python -m pytest tests/ --cov=app -q

# --- Frontend lint (matches: npm run lint) ---
cd "$REPO_ROOT/frontend"
run_step "frontend-lint: eslint" npx eslint .

# --- Frontend build (matches: npm run build -> tsc -b && vite build) ---
run_step "frontend-build: tsc + vite" npm run build

# --- Summary ---
echo
if [[ $FAILED -eq 0 ]]; then
    green "All CI checks passed!"
else
    red "$FAILED CI check(s) failed."
    exit 1
fi
