# Tally Sales Automation MVP

Multi-company TallyPrime sales import product with a Next.js frontend, FastAPI backend, and local agent for Tally connectivity.

## Architecture

- `frontend/`: Next.js app for login, company setup, local-agent status, sync, and import workflows.
- `backend/`: FastAPI API, SQLite persistence, auth/session, company, import, voucher, and sync services.
- `local_agent/`: local FastAPI service that runs on the user's Tally machine and calls the local Tally HTTP endpoint.

The production model is frontend/backend plus a local agent. The backend does not directly call a user's local `localhost:9000`; it sends authorized company-scoped commands to the paired local agent.

## Auth And Companies

- Users sign in with Google through `POST /auth/google`.
- The backend creates server-side sessions using hashed session tokens.
- Product endpoints require authentication.
- Users can create multiple companies.
- Ledgers, stock items, imports, import rows, voucher logs, and duplicate checks are scoped by `company_id`.
- Company settings include Tally URL and ledger defaults.

## Local Agent

The local agent is started on the machine where TallyPrime is available.

Backend endpoints:

- `POST /companies/{company_id}/agents/pairing-token`
- `POST /agents/pair`
- `POST /agents/heartbeat`
- `POST /companies/{company_id}/agents/{agent_id}/revoke`

Agent endpoint:

- `POST /tally/execute`

The agent sends XML payloads to TallyPrime and returns normalized JSON responses to the backend.

## Supported Excel Contract

The MVP accepts `.xlsx` or `.xls` uploads with these required columns:

- `product_name`: exact Tally Stock Item name.
- `price`: positive numeric amount. GST splitting is out of scope, so this amount maps directly to the voucher value.
- `payment_mode`: `Cash` or `UPI`, matched case-insensitively.
- `voucher_date`: accounting voucher date in a parseable date format. API requests should use `YYYY-MM-DD`.

Each row represents one Sales Voucher with quantity fixed at `1`.

## Operator Flow

1. Sign in with Google.
2. Add a Tally company.
3. Pair the local agent running on the Tally machine.
4. Run company sync through `POST /companies/{company_id}/sync`.
5. Upload Excel through `POST /companies/{company_id}/imports/upload`.
6. Process persisted rows through `POST /companies/{company_id}/imports/{import_id}/process`.
7. Commit valid rows through `POST /companies/{company_id}/imports/{import_id}/commit`.
8. Review import history and row-level results.

## Validation Behavior

The backend rejects or flags rows when:

- The user is unauthenticated.
- The company is missing or owned by another user.
- The paired local agent is offline or revoked.
- The company master cache has not been synced.
- The product is not an exact synced Tally Stock Item match.
- Required company-configured ledgers are missing.
- Price, payment mode, or voucher date is invalid.
- The built voucher is not balanced.
- The source row was already committed successfully for that company.

During commit only, the system may create the configured UPI fallback ledger under the configured fallback group. No Stock Items or arbitrary ledgers are auto-created.

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
