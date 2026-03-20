#!/usr/bin/env bash
#
# PAWS Test Runner
#
# Usage:
#   ./scripts/test.sh              # Run unit + integration tests (fast, no Docker)
#   ./scripts/test.sh --cov        # With coverage report
#   ./scripts/test.sh --docker     # Start test services, run full integration suite, tear down
#   ./scripts/test.sh --lint       # Lint + format check only
#   ./scripts/test.sh --all        # Lint + test + coverage
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[FAIL]${NC} $*"; }

# -- Backend tests (fast - in-memory SQLite, mocked services) --------------

run_backend_tests() {
    info "Running backend tests..."
    cd "$BACKEND_DIR"
    source .venv/bin/activate 2>/dev/null || { error "No venv found. Run: cd backend && python -m venv .venv && pip install -e '.[dev]'"; exit 1; }

    local extra_args=()
    if [[ "${COV:-}" == "1" ]]; then
        extra_args+=(--cov=app --cov-report=term-missing --cov-report=html:htmlcov)
    fi

    python -m pytest tests/ -v "${extra_args[@]}" "$@"
    info "Backend tests passed ok"
}

# -- Lint ------------------------------------------------------------------

run_lint() {
    info "Linting backend..."
    cd "$BACKEND_DIR"
    source .venv/bin/activate 2>/dev/null || true

    ruff check app/ tests/
    ruff format --check app/ tests/
    info "Backend lint passed ok"

    info "Type-checking frontend..."
    cd "$FRONTEND_DIR"
    npx tsc --noEmit
    info "Frontend type-check passed ok"
}

# -- Frontend build --------------------------------------------------------

run_frontend_build() {
    info "Building frontend..."
    cd "$FRONTEND_DIR"
    npm run build --quiet
    info "Frontend build passed ok"
}

# -- Docker integration tests ---------------------------------------------

run_docker_tests() {
    info "Starting test services (docker compose --profile test)..."
    cd "$ROOT_DIR"
    docker compose --profile test up -d test-db test-redis

    info "Waiting for test services..."
    sleep 3

    export PAWS_DATABASE_URL="postgresql+asyncpg://paws_test:paws_test@localhost:5433/paws_test"
    export PAWS_REDIS_URL="redis://localhost:6380/0"
    export PAWS_S3_ENDPOINT_URL="http://localhost:7480"
    export PAWS_SECRET_KEY="test-secret-key-not-for-production"

    cd "$BACKEND_DIR"
    source .venv/bin/activate

    info "Running migrations on test DB..."
    alembic upgrade head 2>/dev/null || warn "Migrations skipped (may need initial DB setup)"

    info "Running integration tests against Docker services..."
    python -m pytest tests/ -v --tb=short "$@"

    info "Tearing down test services..."
    cd "$ROOT_DIR"
    docker compose --profile test down -v

    info "Docker integration tests passed ok"
}

# -- Main ------------------------------------------------------------------

case "${1:-}" in
    --lint)
        run_lint
        ;;
    --cov)
        COV=1 run_backend_tests "${@:2}"
        ;;
    --docker)
        run_docker_tests "${@:2}"
        ;;
    --all)
        run_lint
        COV=1 run_backend_tests
        run_frontend_build
        info "All checks passed ok"
        ;;
    --help|-h)
        echo "Usage: $0 [--lint|--cov|--docker|--all|--help]"
        echo ""
        echo "  (no args)   Run unit + integration tests (fast, in-memory SQLite)"
        echo "  --cov       Run tests with coverage report"
        echo "  --docker    Start Docker test services, run full suite, tear down"
        echo "  --lint      Lint (ruff) + type-check (tsc) only"
        echo "  --all       Lint + test with coverage + frontend build"
        ;;
    *)
        run_backend_tests "$@"
        ;;
esac
