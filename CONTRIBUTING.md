# Contributing to PAWS

## Setup

```bash
# Prerequisites: Docker, Python 3.11+, Node.js 22+

# 1. Fork, clone, and branch
git clone <your-fork>
cd Proxmox-Automated-Web-Services
git checkout -b feature/your-change

# 2. Configure
cp .env.example .env   # fill in your values

# 3. Start services
docker compose up -d db redis minio

# 4. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export PAWS_SECRET_KEY=dev-secret-key
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 5. Frontend
cd ../frontend
npm install && npm run dev
```

## Project Layout

- `backend/app/routers/` - API endpoints (one file per domain)
- `backend/app/services/` - Business logic and external integrations
- `backend/app/models/models.py` - SQLAlchemy models
- `backend/app/schemas/schemas.py` - Pydantic schemas
- `frontend/src/pages/` - Page components (one per route)
- `frontend/src/components/` - Shared UI components

New routers -> register in `main.py`. New pages -> add route in `App.tsx`. New models -> create Alembic migration.

## Code Style

**Backend:** Ruff for linting/formatting. Async-first. `snake_case` functions, `PascalCase` classes. Modern Python (`str | None`, f-strings). All config via `PAWS_` env vars.

**Frontend:** TypeScript only. Functional components with hooks. All API calls through `api/client.ts`. Avoid `any`.

```bash
# Check before committing
cd backend && ruff check app/ tests/ && ruff format --check app/ tests/
cd frontend && npm run lint && npx tsc --noEmit
```

## Testing

Tests use in-memory SQLite with mocked external services - no Proxmox/Postgres/Redis needed.

```bash
cd backend && pytest                # all tests
cd frontend && npx tsc --noEmit     # type-check
./scripts/test.sh --all             # everything
```

Test fixtures in `conftest.py`: `client`, `auth_client`, `admin_client`, `mock_proxmox_client`.

## Pull Requests

- Branch from `main`, target `main`
- Keep changes small and focused
- Include tests for new endpoints
- Add new env vars to `.env.example`
- Never commit secrets or `.env` files
- All CI checks must pass
