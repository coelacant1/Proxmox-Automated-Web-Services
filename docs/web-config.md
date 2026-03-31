# PAWS Configuration Guide

## Configuration Methods

PAWS supports two configuration methods that can be used independently or together:

### 1. Setup Wizard (Recommended for new deployments)

On first launch (no admin user exists), PAWS presents a setup wizard at `/setup` where you:

1. Create the initial admin account
2. Set the platform name

After setup, configure everything else through the Admin panel:
- **Infrastructure > Connections** - Add PVE, PBS, and S3 connections
- **System > Auth** - Configure OAuth/OIDC and registration policy
- **System > Settings** - Resource quotas, SMTP, lifecycle policies, etc.

### 2. Environment Variables (.env file)

For headless/automated deployments, configure everything via `.env`. See `.env.example` for all available variables.

**Minimum required in `.env`:**
```
PAWS_SECRET_KEY=<your-jwt-secret>
PAWS_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/paws
PAWS_REDIS_URL=redis://localhost:6379/0
```

Everything else can be configured via the Admin UI after setup.

## Configuration Priority

When both methods are used, the resolution order is:

```
Database (Admin UI) > Environment Variable (.env) > Default Value
```

Specifically:
- If a value is set in the database (via Admin UI), it is always used
- If not set in the database, the corresponding `PAWS_*` environment variable is checked
- If neither is set, built-in defaults apply

This means:
- **Existing `.env` deployments continue working unchanged** - env vars are used as fallback
- **Admin UI changes take effect immediately** - no restart required
- **Sensitive values** (S3 secret key, OAuth client secret, SMTP password) are encrypted at rest in the database using AES-256-GCM

## Encryption

Secrets stored in the database are encrypted using AES-256-GCM. The master key is resolved in order:

1. `PAWS_MASTER_KEY` environment variable (base64url-encoded 32-byte key)
2. `/data/.paws_master_key` file
3. Auto-generated and saved to `/data/.paws_master_key`

To generate a master key manually:
```bash
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

## Cluster Connections

Clusters can be configured via:

| Method | When to use |
|--------|-------------|
| **Admin UI** (Infrastructure > Connections) | Interactive setup, adding/removing clusters at runtime |
| **Environment variables** (`PAWS_CLUSTER_*`) | Automated deployments, CI/CD, Docker Compose |

Both methods can coexist. DB connections are loaded first, then env-based clusters are added as fallbacks (if not already defined in DB).

## Migration from .env-only to Web Config

1. Deploy the update (run `alembic upgrade head`)
2. Log in as admin
3. Go to Admin > Infrastructure > Connections
4. Add your clusters via the UI (test connectivity inline)
5. Go to Admin > System > Settings to configure S3, OAuth, SMTP
6. Optionally remove the corresponding values from `.env`

No downtime required. The system falls back to `.env` values until DB values are set.
