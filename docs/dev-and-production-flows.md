# Dev And Production Flows

This document is the lookup source for how AccountPilot runs in local development versus real production. Keep these flows separate. Do not mix direct-dev assumptions into production, and do not require the Windows Helper flow while doing local Mac testing.

## Mode Summary

AccountPilot has two runtime modes:

| Environment | Backend mode | Frontend mode | Tally access path | Helper download |
| --- | --- | --- | --- | --- |
| Local development | `CONNECTOR_MODE=direct` | `NEXT_PUBLIC_CONNECTOR_MODE=direct` | Backend calls `TALLY_URL` directly | Hidden |
| Production | `CONNECTOR_MODE=polling` | `NEXT_PUBLIC_CONNECTOR_MODE=polling` | Windows Helper polls backend, then calls Tally locally | Required |

## Local Development Flow

Use this mode for Mac development and LAN testing.

Required backend env:

```env
APP_ENV=development
CONNECTOR_MODE=direct
LOCAL_AGENT_BOOTSTRAP_ENABLED=false
TALLY_URL=http://192.168.1.15:9000
```

Required frontend env:

```env
NEXT_PUBLIC_CONNECTOR_MODE=direct
NEXT_PUBLIC_API_URL=
```

In direct mode:

- The frontend must not show the AccountPilot Helper download panel.
- The backend must not bootstrap or call the old local-agent URL such as `127.0.0.1:9100`.
- `/tally/status` calls Tally directly through `TallyClient`.
- `/tally/companies` calls Tally directly and should return the open company list.
- Company creation validates the Tally company directly.
- Master sync reads ledgers and stock items directly.
- Upload and preview use the synced local database cache.
- Commit runs create vouchers directly through the backend.

Expected smoke checks:

```bash
curl -b /tmp/accountpilot-cookies.txt http://127.0.0.1:8000/tally/status
curl -b /tmp/accountpilot-cookies.txt http://127.0.0.1:8000/tally/companies
```

Expected responses:

```json
{"status":"connected","detail":null,"message":"Connected to Tally"}
{"available":true,"companies":["Bhrama Enterprises"],"detail":null,"message":null}
```

## Production Flow

Use this mode for real users.

Required backend env:

```env
APP_ENV=production
CONNECTOR_MODE=polling
LOCAL_AGENT_BOOTSTRAP_ENABLED=false
LEGACY_ENDPOINTS_ENABLED=false
ALLOW_DEV_AUTH=false
COOKIE_SECURE=true
COOKIE_SAMESITE=none
```

Required frontend env:

```env
NEXT_PUBLIC_CONNECTOR_MODE=polling
NEXT_PUBLIC_HELPER_DOWNLOAD_URL=https://downloads.your-domain.com/AccountPilotHelperSetup.exe
```

In polling mode:

- The frontend shows AccountPilot Helper onboarding when no Helper is connected.
- The backend creates short-lived setup sessions for Helper registration.
- The Helper stores its agent credentials and polls the backend over outbound HTTPS.
- The cloud backend never tries to call a user's `localhost` or LAN IP directly.
- Tally access happens on the Windows machine running Helper.
- Company discovery, company validation, health checks, master sync, and voucher creation are all connector jobs.
- The user sees one frontend action for committing rows: `Commit rows`.

## Production Safety Guards

Backend startup intentionally fails in production if:

- `CONNECTOR_MODE` is not `polling`.
- `LOCAL_AGENT_BOOTSTRAP_ENABLED=true`.
- `ALLOW_DEV_AUTH=true`.

These guards exist to prevent a production deploy from silently using local development behavior.

## Current Local Test Setup

Current known-good local setup:

```env
TALLY_URL=http://192.168.1.15:9000
CONNECTOR_MODE=direct
NEXT_PUBLIC_CONNECTOR_MODE=direct
```

Known-good live checks from May 18, 2026:

- Tally status: connected.
- Company discovery: `Bhrama Enterprises`.
- Company creation: succeeded.
- Master sync: 66 ledgers and 20 stock items.

## Troubleshooting

If login succeeds but the next API call says the session expired:

- Use one browser hostname consistently, either `http://localhost:3000` or `http://127.0.0.1:3000`.
- With no `NEXT_PUBLIC_API_URL`, the frontend chooses the backend hostname from the browser URL.
- Clear browser site data for both `localhost` and `127.0.0.1` if cookies are stale.

If local dev says Tally is disconnected:

- Confirm backend env has `CONNECTOR_MODE=direct`.
- Confirm backend env has the reachable `TALLY_URL`.
- Confirm backend logs do not mention `127.0.0.1:9100`.
- Check `GET /tally/status` and `GET /tally/companies` directly.

If production does not show the Helper download:

- Confirm frontend env has `NEXT_PUBLIC_CONNECTOR_MODE=polling`.
- Confirm frontend env has `NEXT_PUBLIC_HELPER_DOWNLOAD_URL`.
- Confirm the frontend was rebuilt after env changes.

If production tries direct Tally:

- Stop the deploy.
- Confirm `APP_ENV=production`.
- Confirm startup guards are active.
- Confirm `CONNECTOR_MODE=polling`.
