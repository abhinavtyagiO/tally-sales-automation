# AccountPilot

AccountPilot is a multi-company sales voucher automation product for TallyPrime. It has a Next.js frontend, FastAPI backend, SQLite persistence, and a Windows desktop helper that runs beside Tally.

The current product supports:

- Google sign-in and company-scoped data.
- Guided onboarding for Tally connection and company setup.
- AccountPilot Helper for local Tally connectivity.
- Ledger and stock group sync, with stock items synced per group.
- Excel upload and preview.
- Single voucher creation from the UI.
- Multi-item vouchers.
- Invoice for Individual Customers, with GST-inclusive pricing and CGST/SGST splitting.
- Invoice for GST Firms, with buyer GSTIN/state details and CGST/SGST or IGST calculation.

## Architecture

- `frontend/`: Next.js app for login, onboarding, dashboard, inventory, Excel upload, preview/commit, history, and single voucher creation.
- `backend/`: FastAPI API, auth/session handling, SQLite persistence, company setup, import processing, voucher building, connector job orchestration, and Tally response handling.
- `connector/`: packaged Windows Helper source. The helper runs on the user's Windows/Tally machine, polls the backend for company-scoped jobs, talks to the local Tally HTTP endpoint, and posts results back.
- `local_agent/`: development/local testing agent retained for local workflows.
- `tests/`: backend, connector runtime, and frontend derivation coverage.

Production connectivity is web app plus AccountPilot Helper. The hosted backend does not call a user's local `localhost:9000` directly. It queues authorized work for the paired helper, and the helper performs local Tally operations.

## User Flow

1. User signs in with Google.
2. User installs/runs AccountPilot Helper during onboarding.
3. The helper connects to the backend and checks local Tally availability.
4. User selects or enters a Tally company with GSTIN and state.
5. Backend/helper sync ledgers and stock groups.
6. Stock items sync asynchronously by stock group.
7. User uploads an Excel file or creates a single voucher in the app.
8. Backend validates rows/items against synced Tally masters.
9. User previews voucher rows and commits valid vouchers.
10. Helper creates required ledgers when needed, posts vouchers to Tally, and returns success/failure status.

## Authentication And Company Scope

- Users sign in through `POST /auth/google`.
- Backend sessions use hashed session tokens.
- Product endpoints require authentication.
- Users can manage multiple companies.
- Ledgers, stock groups, stock items, imports, import rows, connector jobs, voucher logs, and duplicate checks are scoped by `company_id`.
- Company settings include Tally URL, GST details, and ledger defaults/mappings.

## Tally And Helper Connectivity

The Windows Helper is the normal production bridge to Tally. It is packaged as `AccountPilotHelper.exe` and `AccountPilotHelperSetup.exe`.

Important helper behavior:

- Installs locally on the Tally machine.
- Registers/pairs with the backend using onboarding setup data.
- Auto-starts on Windows login.
- Polls backend connector jobs.
- Sends XML requests to the configured local Tally HTTP endpoint.
- Returns compact job results to the backend.

Common connector job types include:

- `sync_ledgers`
- `sync_stock_groups`
- `sync_stock_items_for_group`
- `create_ledger`
- `create_sales_voucher`
- `health_check`

## Inventory Sync

The app no longer syncs all stock items as one large blocking operation.

Current behavior:

- Initial onboarding sync fetches ledgers and stock groups.
- Stock items are fetched per stock group in background connector jobs.
- Inventory UI shows stock groups first.
- Users can open a stock group to view paginated stock items.
- Failed stock groups can be retried manually.
- Voucher creation/upload is gated until stock item sync is terminal enough for reliable product matching.

Stock item matching uses the synced Tally stock item canonical name for voucher creation. Display names and part numbers may be shown in the UI for search/readability, but voucher XML still uses the canonical Tally stock item name.

## Voucher Types

### Invoice For Individual Customers

Used for walk-in/normal customer sales.

Voucher context:

- `voucher_date`
- `payment_mode`
- one or more stock items

Each item has:

- `product_name`
- `quantity`
- total selling price for that line quantity

Pricing is GST-inclusive. For example, quantity `2` and price `200` means 2 units were sold for a total of `200`, not `200` per unit. The backend calculates taxable amount and splits same-state GST into CGST/SGST.

### Invoice For GST Firms

Used for registered business buyers.

Voucher context:

- `voucher_date`
- `buyer_name`
- `buyer_gstin`
- `buyer_state`
- optional buyer address/place of supply
- one or more stock items

Each item has:

- `product_name`
- `quantity`
- total selling price for that line quantity

Single-voucher GST firm pricing is GST-inclusive. Same-state sales use CGST/SGST. Inter-state sales use IGST.

## Multi-Item Vouchers

One voucher can contain multiple stock items.

Example:

- 2 units of `stock-a` for total line amount `200`
- 2 units of `stock-b` for total line amount `400`

The backend builds one voucher with two `InventoryEntries`, sums taxable/GST/invoice totals, and sends one `create_sales_voucher` job to the helper.

Partial item-level commit is not supported inside a voucher. If a grouped voucher fails, all rows/items belonging to that voucher are marked failed.

## Excel Upload Contract

The app accepts `.xlsx` and `.xls` files.

### Invoice For Individual Customers

Required columns:

- `product_name`
- `price`
- `payment_mode`
- `voucher_date`

Optional columns:

- `quantity` defaults to `1`
- `voucher_id` groups multiple rows into one voucher

`price` is the GST-inclusive total selling price for that row's quantity.

### Invoice For GST Firms

Required columns:

- `voucher_date`
- `buyer_name`
- `buyer_gstin`
- `buyer_state`
- `product_name`
- `quantity`
- `rate`
- `payment_mode`

Optional columns:

- `buyer_address`
- `place_of_supply`
- `voucher_id` groups multiple rows into one voucher

For uploaded GST firm Excel rows, `rate` remains the taxable per-unit rate for backward compatibility with the existing upload contract. The single-voucher UI uses inclusive line totals.

### Grouping With `voucher_id`

If `voucher_id` is absent, each Excel row remains one voucher, preserving old behavior.

If multiple rows share the same `voucher_id`, they become one voucher with multiple inventory entries. Rows in the same group must have the same voucher-level context:

- same voucher date
- same payment mode
- same buyer fields for GST firm invoices

## Validation Behavior

The backend rejects or flags rows/items when:

- The user is unauthenticated.
- The company is missing or owned by another user.
- AccountPilot Helper is not connected when a helper job is required.
- Tally cannot be reached from the helper.
- Company master data has not been synced.
- Stock items are still syncing when product matching is required.
- Product name does not match a synced Tally stock item.
- GST rate is missing for a taxable stock item.
- Required company-configured ledgers are missing or cannot be created.
- Price, quantity, payment mode, buyer GSTIN/state, or voucher date is invalid.
- Rows with the same `voucher_id` have conflicting voucher-level fields.
- The built voucher is not balanced.

Duplicate-looking sales rows are allowed because the same item can be sold multiple times. Duplicate prevention is based on source fingerprints during commit, not broad row de-duplication.

## Tally Posting

Voucher builders produce Tally-facing payloads with:

- `VoucherTypeName`
- `Date`
- party/payment ledger details
- tax ledger details
- `InventoryEntries`
- `LedgerEntries` where applicable
- source metadata for idempotency and row status tracking

`backend/services/tally_client.py` converts those payloads into Tally XML. The XML path already supports multiple inventory entries.

## Helper Releases

A new AccountPilot Helper build/release is required when changing:

- `connector/**`
- shared code imported by the helper
- especially `backend/services/tally_client.py`, because `connector/main.py` packages it

Changes limited to backend route orchestration, frontend UI, Excel parsing, voucher builders, or tests do not automatically require a helper release unless helper-packaged code is touched.

The helper workflow is `.github/workflows/windows-helper.yml`. It runs on PRs only when helper-relevant paths change.

## Development

Install Python dependencies in the project virtualenv and frontend dependencies with pnpm.

Backend tests:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/accountpilot-pycache .venv/bin/python -m unittest tests.test_mvp_flow tests.test_connector_runtime
```

Focused parent flow tests:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/accountpilot-pycache .venv/bin/python -m unittest tests.test_parent2_flow
```

Some parent flow tests expect a reachable Tally endpoint and may fail or hang if Tally is not available.

Frontend tests/build:

```bash
pnpm -C frontend test:derivations
pnpm -C frontend build
```

Backend:

```bash
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Local development agent:

```bash
.venv/bin/python -m uvicorn local_agent.main:app --reload --host 127.0.0.1 --port 9100
```

Frontend:

```bash
pnpm -C frontend run dev
```

## Non-Goals

- Automatic Stock Item creation.
- Fuzzy product matching for voucher creation.
- Customer ledger CRM beyond voucher party/buyer fields.
- Bank reconciliation.
- Cost centers.
- Sharing companies across users.
- Organization/team accounts.
- Password login.
- Cloud-to-local Tally networking without a locally installed helper.
