# AccountPilot Deployment Runbook

This runbook prepares AccountPilot for deployment without choosing a specific hosting provider. Use it to compare providers and then translate the same requirements into that provider's UI, CLI, or infrastructure code.

## Services

Deploy three artifacts:

1. Backend API: FastAPI app from `backend/Dockerfile`.
2. Frontend web app: Next.js app from `frontend/Dockerfile`.
3. AccountPilot Helper: Windows installer from `connector/packaging`.

## Production Runtime Model

Production must use polling connector mode.

```text
Browser -> Frontend -> Backend API <- AccountPilot Helper -> Tally
```

The cloud backend must never call a customer LAN IP or `localhost` directly. The Windows Helper polls the backend over outbound HTTPS and calls Tally locally from the customer's machine.

## Backend Requirements

Required:

- One backend instance if using SQLite.
- Persistent disk mounted at `/data`.
- HTTPS at the public API domain.
- CORS configured for the frontend origin.
- Google OAuth client configured for the deployed frontend origin.
- Regular backup of `/data/tally_sales.db`.

Use `deployment/backend.env.example` as the source env template.

Important production values:

```env
APP_ENV=production
CONNECTOR_MODE=polling
LOCAL_AGENT_BOOTSTRAP_ENABLED=false
LEGACY_ENDPOINTS_ENABLED=false
ALLOW_DEV_AUTH=false
COOKIE_SECURE=true
COOKIE_SAMESITE=none
SQLITE_DB_PATH=/data/tally_sales.db
```

Backend startup intentionally fails if production is configured with unsafe dev settings.

## Frontend Requirements

Use `deployment/frontend.env.example` as the source env template.

Important production values:

```env
NEXT_PUBLIC_API_URL=https://api.your-domain.com
NEXT_PUBLIC_GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
NEXT_PUBLIC_ENABLE_DEV_LOGIN=false
NEXT_PUBLIC_CONNECTOR_MODE=polling
NEXT_PUBLIC_HELPER_DOWNLOAD_URL=https://downloads.your-domain.com/AccountPilotHelperSetup.exe
```

These values are build-time values for Next.js. Rebuild the frontend image after changing them.

## SQLite Deployment Constraint

SQLite is acceptable for a controlled pilot if:

- There is exactly one backend writer.
- The DB file is on persistent storage.
- Backups are configured.
- The backend is not horizontally scaled.

Do not use SQLite on ephemeral filesystems. Move to Postgres before multi-instance production or broader rollout.

## Build Images

From the repository root:

```bash
docker build -f backend/Dockerfile -t accountpilot-backend:latest .
docker build \
  -f frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_URL=https://api.your-domain.com \
  --build-arg NEXT_PUBLIC_GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com \
  --build-arg NEXT_PUBLIC_CONNECTOR_MODE=polling \
  --build-arg NEXT_PUBLIC_HELPER_DOWNLOAD_URL=https://downloads.your-domain.com/AccountPilotHelperSetup.exe \
  -t accountpilot-frontend:latest .
```

## Run Locally In Production Shape

Backend:

```bash
docker run --rm -p 8000:8000 \
  -v accountpilot-data:/data \
  --env-file deployment/backend.env.example \
  accountpilot-backend:latest
```

Frontend:

```bash
docker run --rm -p 3000:3000 accountpilot-frontend:latest
```

For a real provider, do not use the example files directly. Copy the values into provider-managed environment variables and replace placeholders.

## Health Checks

Backend:

```bash
curl https://api.your-domain.com/health
```

Expected:

```json
{"status":"ok"}
```

Frontend:

```bash
curl https://app.your-domain.com
```

Expected: HTTP 200 with the Next.js app.

## Helper Build

On Windows:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\connector\packaging\build_windows.ps1
```

Then build the installer with Inno Setup using:

```text
connector\packaging\AccountPilotHelper.iss
```

Upload the resulting installer to the URL configured as `NEXT_PUBLIC_HELPER_DOWNLOAD_URL`.

For full first-run pairing, the installer must be launched with the setup parameters created by web onboarding:

```powershell
AccountPilotHelperSetup.exe /BACKEND_URL=https://api.your-domain.com /SETUP_TOKEN=one-time-token /TALLY_URL=http://127.0.0.1:9000
```

The installed Helper exchanges the setup token at `/connector/register`, saves credentials to `%LOCALAPPDATA%\AccountPilot Helper\config.json`, and then uses those saved credentials for future polling and Windows auto-start.

## Pre-Deploy Checklist

- Backend image builds.
- Frontend image builds.
- Backend production config guard passes with production env.
- Backend production config guard fails with unsafe direct mode.
- Persistent storage is attached to `/data`.
- Frontend `NEXT_PUBLIC_API_URL` points to the deployed API.
- Backend `CORS_ALLOWED_ORIGINS` includes the deployed frontend.
- Google OAuth authorized JavaScript origins include the deployed frontend.
- Google OAuth backend client ID matches both frontend and backend env.
- Helper installer URL is reachable.
- Backups are enabled for `/data/tally_sales.db`.

## Rollback

Rollback is service-specific:

- Keep the previous backend image tag.
- Keep the previous frontend image tag.
- Back up `/data/tally_sales.db` before migrations or risky releases.

Do not roll back the DB file unless you intentionally accept losing data created after the backup.
