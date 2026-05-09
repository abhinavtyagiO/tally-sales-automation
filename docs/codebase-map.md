# Codebase Map And Refactor Backlog

This project is currently a small MVP, but a few files have grown into mixed-responsibility modules. This map documents the current boundaries and the safest next refactors.

## Runtime Shape

- `frontend/`: Next.js UI for auth, Tally connection status, company setup, Excel preview, and commit summary.
- `backend/api/routes.py`: FastAPI route layer plus several workflow helpers.
- `backend/services/`: product logic for auth, Tally connectivity, sync, Excel parsing, voucher building, and local connector dispatch.
- `backend/db/database.py`: SQLite schema, migrations, and all persistence functions.
- `local_agent/`: trusted connector that talks to Tally over HTTP/XML.
- `tools/fetch_tally_reference.py`: local-only reference dump tool for inspecting Tally XML contracts.

## Current Hotspots

### `backend/api/routes.py`

This file owns routing, request validation, workflow orchestration, import processing, commit logic, legacy prototype endpoints, and error translation.

Recommended split:

- `backend/api/auth_routes.py`
- `backend/api/company_routes.py`
- `backend/api/import_routes.py`
- `backend/api/agent_routes.py`
- `backend/services/company_setup_service.py`
- `backend/services/import_workflow_service.py`
- `backend/services/commit_service.py`

Keep FastAPI handlers thin: parse request, call service, return response.

### `backend/db/database.py`

This file mixes schema creation, migrations, session persistence, company persistence, master cache persistence, import rows, voucher logs, and legacy metadata.

Recommended split:

- `backend/db/schema.py`
- `backend/repositories/users.py`
- `backend/repositories/sessions.py`
- `backend/repositories/companies.py`
- `backend/repositories/local_agents.py`
- `backend/repositories/masters.py`
- `backend/repositories/imports.py`
- `backend/repositories/voucher_logs.py`

Keep `database.py` as a temporary facade while moving functions gradually, so existing tests keep passing during migration.

### `backend/services/tally_client.py`

This file currently combines HTTP transport, Tally response validation, XML parsing, generic XML serialization, collection extraction, and voucher XML building.

Recommended split:

- `backend/services/tally_transport.py`: HTTP GET/POST, timeouts, response status.
- `backend/services/tally_xml.py`: XML sanitization, XML-to-dict conversion, collection extraction.
- `backend/services/tally_contracts.py`: request XML builders for collection export, report export, voucher import.
- `backend/services/tally_client.py`: small facade with business-friendly methods.

This is the highest-value backend refactor because Tally contracts are the most volatile part of the product.

### `frontend/app/page.tsx`

This file currently contains the full app: auth, shell, connection status, company setup, import flow, preview table, commit summary, and API helpers.

Recommended split:

- `frontend/app/page.tsx`: route entry only.
- `frontend/app/api.ts`: typed fetch wrapper and API functions.
- `frontend/app/components/LoginPanel.tsx`
- `frontend/app/components/Sidebar.tsx`
- `frontend/app/components/TallyConnection.tsx`
- `frontend/app/components/CompanySetup.tsx`
- `frontend/app/components/ImportWorkflow.tsx`
- `frontend/app/components/PreviewTable.tsx`
- `frontend/app/components/CommitSummary.tsx`
- `frontend/app/types.ts`

This will make browser issues easier to isolate and make AI edits much less likely to collide.

## Testability Gaps

- Tally voucher XML should have golden-file tests for the exact XML sent to Tally.
- Tally response parsing should be tested against saved raw XML from `tally_reference/`.
- Company setup should test rollback when validation succeeds but initial sync fails.
- Commit should distinguish Tally `CREATED=1` from `EXCEPTIONS>0`; this now happens in code and should have a focused unit test.
- Frontend needs at least one browser-level smoke path: Google/dev auth guard, company setup error, upload preview, commit summary.

## Safe Refactor Order

1. Extract Tally XML helpers from `tally_client.py`.
2. Add golden XML tests for Sales voucher import.
3. Split import/commit workflow out of `routes.py`.
4. Split repository functions out of `database.py` behind a facade.
5. Split `frontend/app/page.tsx` into components and `api.ts`.
6. Remove legacy prototype endpoints after frontend no longer uses them.

## Known Product/Architecture Decisions

- The local connector is trusted product infrastructure, not a user-facing setup surface.
- Company name is user-provided or selected from Tally discovery when available.
- Backend owns Tally validation, master sync, preview validation, and commit.
- Duplicate-looking sales rows are allowed.
- Current successful voucher write uses Tally `Accounting Voucher View`; inventory invoice XML needs a separate contract pass before stock-impacting voucher creation is considered reliable.
