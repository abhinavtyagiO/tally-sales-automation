# Tally Sales Automation MVP

Multi-company TallyPrime sales import product with a Next.js frontend, FastAPI backend, and local agent for Tally connectivity.

## Architecture

- `frontend/`: Next.js app for Google login, Tally connection status, company setup, Excel preview, and commit workflows.
- `backend/`: FastAPI API, SQLite persistence, auth/session, company, import, voucher, and sync services.
- `local_agent/`: local FastAPI service that runs on the user's Tally machine and calls the local Tally HTTP endpoint.

The production model is frontend/backend plus a local connector. The backend does not directly call a user's local `localhost:9000`; it sends authorized company-scoped commands to the trusted local connector. The connector is internal product infrastructure and should not be exposed as a normal user workflow.

## Auth And Companies

- Users sign in with Google through `POST /auth/google`.
- The backend creates server-side sessions using hashed session tokens.
- Product endpoints require authentication.
- Users can create multiple companies.
- Ledgers, stock items, imports, import rows, voucher logs, and duplicate checks are scoped by `company_id`.
- Company settings include Tally URL and ledger defaults.

## Tally Connection

The local connector runs on the machine or office LAN where TallyPrime is available. User-facing UI should describe this only as the Tally connection. Normal users should not see pairing tokens, connector URLs, local ports, or manual connector setup steps.

In local development, the backend can bootstrap a connector at `LOCAL_AGENT_URL=http://localhost:9100`. In production, disable this with `LOCAL_AGENT_BOOTSTRAP_ENABLED=false`. A cloud backend cannot reach a user's `localhost`; the connector must register a backend-reachable HTTPS `base_url`, usually through the packaged connector's tunnel/relay layer. The backend then calls that connector URL, and the connector calls Tally at its own local `TALLY_URL` such as `http://127.0.0.1:9000`.

The Tally URL is stored with the company but is evaluated by the connector machine. Do not configure production backend `TALLY_URL` to a developer LAN IP such as `192.168.x.x`.

Backend endpoints:

- `GET /tally/status`
- `GET /tally/companies`
- `POST /agents/pairing-token`
- `POST /companies/{company_id}/agents/pairing-token`
- `POST /agents/pair`
- `POST /agents/heartbeat`
- `POST /companies/{company_id}/agents/{agent_id}/revoke`

Agent endpoint:

- `POST /tally/execute`

The connector sends XML payloads to TallyPrime and returns normalized JSON responses to the backend. Pairing endpoints remain backend/operations plumbing, not a normal frontend workflow.

For a production connector tunnel, set `LOCAL_AGENT_TOKEN` on the connector to the `agent_auth_token` returned by `POST /agents/pairing-token`. The backend stores that token and sends it as `X-AccountPilot-Agent-Token` when calling `/tally/execute`.

## Production Configuration

Use `deployment/backend.env.example`, `deployment/frontend.env.example`, and `deployment/local-agent.env.example` as the deployment starting point.

Backend production requirements:

- `APP_ENV=production`
- `GOOGLE_CLIENT_ID=<google oauth client id>`
- `CORS_ALLOWED_ORIGINS=https://<frontend-domain>`
- `COOKIE_SECURE=true`
- `COOKIE_SAMESITE=none` when frontend and API are on different sites; use `lax` when they share the same site.
- `LOCAL_AGENT_BOOTSTRAP_ENABLED=false`
- `LEGACY_ENDPOINTS_ENABLED=false`

Frontend production requirements:

- `NEXT_PUBLIC_API_URL=https://<backend-domain>`
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID=<same google oauth client id>`
- `NEXT_PUBLIC_ENABLE_DEV_LOGIN=false`

Local connector production requirements:

- `TALLY_URL=http://127.0.0.1:9000`, unless Tally listens elsewhere on the user's machine/LAN.
- `LOCAL_AGENT_TOKEN=<agent_auth_token from backend pairing>`.
- A backend-reachable HTTPS connector URL must be registered through pairing/heartbeat as `base_url`.

## Supported Excel Contract

The MVP accepts `.xlsx` or `.xls` uploads with these required columns:

- `product_name`: exact Tally Stock Item name.
- `price`: positive numeric amount. GST splitting is out of scope, so this amount maps directly to the voucher value.
- `payment_mode`: payment ledger mode, matched case-insensitively. `Cash` and `UPI` have default ledger mappings, and additional modes can be configured per company.
- `voucher_date`: accounting voucher date in a parseable date format. API requests should use `YYYY-MM-DD`.

Each row represents one Sales Voucher with quantity fixed at `1`.

## Product Flow

1. Sign in with Google.
2. Review the simple Tally connection status.
3. Add a Tally company from a discovered list when available, or type the company name.
4. Backend verifies the company in Tally, saves it, selects it as active, and runs the initial ledgers/stock-items sync.
5. Select the active company when multiple companies exist.
6. Upload Excel through `POST /companies/{company_id}/imports/upload`.
7. Backend runs a quick master sync, parses the Excel, validates persisted rows, and returns a preview.
8. Review row-level ready/error results in the frontend.
9. Commit all valid rows through `POST /companies/{company_id}/imports/{import_id}/commit`.
10. Review success/failure summary and row-level commit errors.

## Validation Behavior

The backend rejects or flags rows when:

- The user is unauthenticated.
- The company is missing or owned by another user.
- Tally cannot be reached through the trusted connector.
- The company master cache has not been synced.
- The product is not an exact synced Tally Stock Item match.
- Required company-configured ledgers are missing.
- Price, payment mode, or voucher date is invalid.
- The built voucher is not balanced.
- The active company is missing or owned by another user.

Duplicate-looking sales rows are allowed because the same item can be sold more than once on the same day. During commit only, the system creates missing configured ledgers needed for the voucher, such as the sales ledger or payment ledgers. No Stock Items are auto-created.

## Tally Transport

Tally master sync uses company-scoped collection export XML with `SVCURRENTCOMPANY={company_name}` and `SVEXPORTFORMAT=XML`.

## Development

Backend tests:

```bash
env PYTHONPYCACHEPREFIX=/Users/abhinav/Desktop/tally-sales-automation-mvp/.pycache .venv/bin/python -m unittest discover -s tests
```

Frontend build:

```bash
cd frontend
pnpm install
pnpm run build
```

Local agent:

```bash
.venv/bin/uvicorn local_agent.main:app --reload --port 9100
```

Backend:

```bash
.venv/bin/uvicorn backend.main:app --reload --port 8000
```

## Non-Goals

- GST handling or tax ledger splitting.
- Multi-item invoices.
- Customer-level party tracking.
- Bank reconciliation.
- Cost centers.
- Automatic Stock Item creation.
- Fuzzy product matching.
- Sharing companies across users.
- Organization/team accounts.
- Password login.
- Cloud-to-local Tally networking without a local agent.
