# pAWS - Proxmox Automated Web Services

[![CI](https://github.com/coelacant1/Proxmox-Automated-Web-Services/actions/workflows/ci.yml/badge.svg)](https://github.com/coelacant1/Proxmox-Automated-Web-Services/actions/workflows/ci.yml)

A self-hosted, AWS-like infrastructure platform built on Proxmox VE. Provides multi-tenant compute, networking, storage, backups, and monitoring through a web UI and REST API.

> [!WARNING]
> This is heavily work-in-progress and not usable. Currently, all features work except for Networking finalization/Endpoints/Firewall. I am just working through building the user interface as well as working out features one-by-one as I link them to the UI.

![Dashboard](assets/ui_example1.png)

## Targeted Features

- **Compute** - VMs and LXC containers from templates, full lifecycle, web console (noVNC/xterm.js), snapshots, import/export
- **Networking** - VPCs with subnets, security groups, service endpoints, DNS
- **Storage** - S3-compatible object storage (Ceph RadosGW) with file browser, sharing, presigned URLs
- **Backups** - PBS integration, scheduled plans, point-in-time restore
- **Monitoring** - Per-resource metrics, alarms, log aggregation
- **Auth** - Local accounts (JWT) + OAuth2/OIDC, RBAC (Admin/Operator/Member/Viewer)
- **Admin** - User management, template catalog, quotas, audit logging

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4 |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2 (async), Pydantic v2 |
| Database | PostgreSQL 16 |
| Cache/Queue | Redis 7, Celery |
| Storage | Ceph RadosGW, Proxmox Backup Server |
| Hypervisor | Proxmox VE 8+ |

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/coelacant1/Proxmox-Automated-Web-Services.git
cd Proxmox-Automated-Web-Services
cp .env.example .env    # set PAWS_SECRET_KEY (required); see "Environment Variables"

# 2. Start everything
docker compose up -d

# 3. Run migrations
docker compose exec backend alembic upgrade head

# 4. Create the initial admin account
#    Open http://localhost:8000/setup in a browser and follow the wizard.
#    (Fallback: if you skip the wizard, an admin password is auto-generated on
#    first boot - find it with: docker compose logs backend | grep "admin account")

# 5. Add your Proxmox cluster via the UI
#    Admin > Infrastructure > Connections (PVE token + optional PBS/S3 creds)
```

**Access:**
Web UI at `http://localhost:5173`
API docs at `http://localhost:8000/docs`, `http://localhost:8000/redoc`, and `http://localhost:8000/openapi.json`

![Container Overview](assets/ui_example2.png)

![VNC Console](assets/ui_example3.png)

![Administration](assets/ui_example4.png)

## Local Development

Run Postgres and Redis in Docker, the backend / Celery / frontend on the host
for fast reloads.

```bash
# 1. Data services (Postgres + Redis)
sudo docker compose up -d db redis

# 2. Environment - generate keys once and persist them in .env
cp .env.example .env
echo "PAWS_SECRET_KEY=$(openssl rand -hex 32)" >> .env
echo "PAWS_MASTER_KEY=$(python -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')" >> .env
# Point the backend at the dockerized DB/Redis on localhost:
echo "PAWS_DATABASE_URL=postgresql+asyncpg://paws:paws@localhost:5432/paws" >> .env
echo "PAWS_REDIS_URL=redis://localhost:6379/0" >> .env

# 3. Backend (FastAPI)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
# Load .env into the shell, then run uvicorn:
set -a && source ../.env && set +a
python -m uvicorn app.main:app --reload --port 8000

# 4. Celery worker + beat (separate terminals, same venv & .env)
cd backend
source .venv/bin/activate              # if you made the venv
set -a && source ../.env && set +a
python -m celery -A app.worker.celery_app worker --loglevel=info

cd backend
source .venv/bin/activate              # if you made the venv
set -a && source ../.env && set +a
python -m celery -A app.worker.celery_app beat --scheduler redbeat.RedBeatScheduler --loglevel=info

# 5. Frontend (separate terminal)
cd frontend
npm install && npm run dev   # http://localhost:5173, proxies API calls to :8000
```

### First-run setup

1. Open `http://localhost:8000/setup` once to create the initial admin account
   (or grab the auto-generated password from the backend logs).
2. Sign in to the UI (`http://localhost:5173`) and go to
   **Admin > Infrastructure > Connections** to add your Proxmox cluster
   (PVE host + API token; optional PBS / S3). Credentials are AES-256-GCM
   encrypted at rest with `PAWS_MASTER_KEY`.

### Notes

- **Run Celery locally too.** Beat warms hot Proxmox caches every ~10s; without
  it, list pages (VMs, LXCs, Resources) hit Proxmox cold and feel slow.
- **`PAWS_MASTER_KEY` must be stable.** If it changes, all encrypted DB
  credentials become unreadable and connections must be re-added. Keep the
  same value in `.env` for both the host backend and any docker compose runs.
- **`uvicorn` not on PATH?** Use `python -m uvicorn ...` from inside the venv.
- **Skip Docker for backend hot-reload.** Keep `db` + `redis` in compose; run
  `backend` / `celery-worker` / `celery-beat` on the host so code edits reload
  instantly without a rebuild.

## Testing

```bash
cd backend && pytest                # unit/integration tests (mocked deps, no external services)
cd frontend && npx tsc --noEmit     # type-check
./scripts/test.sh --all             # lint + tests + coverage + build
```

## Environment Variables

All use the `PAWS_` prefix. See `.env.example` for the full list. Proxmox /
PBS / S3 connections are **not** in `.env` - add them via
**Admin > Infrastructure > Connections** (encrypted in the database).

| Variable | Description |
|----------|-------------|
| `PAWS_SECRET_KEY` | JWT signing key (required; generate with `openssl rand -hex 32`) |
| `PAWS_MASTER_KEY` | AES-256-GCM key for encrypting DB-stored secrets (auto-generated on first run if unset; persist it to keep cluster credentials readable across restarts) |
| `PAWS_DATABASE_URL` | PostgreSQL connection string (e.g. `postgresql+asyncpg://paws:paws@localhost:5432/paws`) |
| `PAWS_REDIS_URL` | Redis connection string (e.g. `redis://localhost:6379/0`) |
| `PAWS_LOCAL_AUTH_ENABLED` | Allow username/password accounts |
| `PAWS_OAUTH_ENABLED` | Enable OIDC SSO (Authentik etc.) |
| `PAWS_CORS_ORIGINS` | Comma-separated list of allowed UI origins |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

See [LICENSE](LICENSE).
