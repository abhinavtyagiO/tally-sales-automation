# Frontend MVP Brief

Build a Next.js frontend for the Tally Sales Automation product and integrate it with the backend. The frontend should provide a smooth, non-technical user experience. Users should not need to understand the local connector, pairing, sync internals, or Tally transport details.

## Product Principles

- The local connector is the trusted Tally connector, not a frontend convenience.
- The frontend must use backend APIs only for product workflows.
- The frontend must not call the local connector directly.
- User-facing copy should say "Tally connection" or "Tally", not "agent", "local agent", "connector setup", or "pairing".
- Users should not be asked to install, start, pair, or configure technical connector details in the normal flow.
- If Tally cannot be reached, show a simple user-facing message such as "Can't connect to Tally right now. Please try again or contact support."

## Deployment Topology

- Web frontend can be hosted remotely or run locally during development.
- Backend can be hosted remotely or run locally during development.
- The local connector runs on the user's machine or office LAN beside Tally.
- Backend coordinates work with the local connector.
- The local connector performs Tally operations:
  - Tally health checks
  - company verification
  - company list lookup when available
  - ledger sync
  - stock item sync
  - voucher posting

## Authentication

- Use real Google OAuth login through Google Identity Services.
- Frontend renders the official Google sign-in button using `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.
- Frontend posts the Google ID token to backend `POST /auth/google`.
- Backend verifies the ID token against Google using `GOOGLE_CLIENT_ID`.
- Backend creates an HttpOnly cookie session.
- Frontend uses `credentials: "include"` for authenticated backend requests.
- Sign-out must revoke the server-side session and clear frontend state.

### Dev Login

- Local-dev email login must not appear by default.
- If needed, dev login can be enabled only when:
  - frontend `NEXT_PUBLIC_ENABLE_DEV_LOGIN=true`
  - backend `ALLOW_DEV_AUTH=true`
- Backend must reject `test:<email>` tokens unless dev auth is explicitly enabled.

## Required Screens And Workflows

### Login

- Show Google sign-in by default.
- If Google OAuth is not configured, show a blocking setup error rather than a fake login form.
- Persist authenticated session through backend cookie auth.
- Show signed-in user identity after login.
- Provide working sign-out.
- If login succeeds but fetching authenticated data fails with `401`, return to login and show a clear session error.

### Dashboard

- Show simple Tally connection status:
  - connected
  - cannot connect to Tally
- Do not expose connector pairing, local URLs, or technical diagnostics to users.
- Check Tally connection status on dashboard load and through a manual refresh action.
- Do not continuously poll in the MVP.

### Company Setup

- Let the user add more than one Tally company.
- Let the user select any saved company as active.
- Persist active company selection per user in the backend.
- If backend/local connector can list Tally companies reliably, show a dropdown.
- If company list is unavailable, fall back to a typed company name.
- The typed company name is still a valid source of truth.
- Users can type company name even if Tally is currently disconnected, but the company must not be saved unless backend verification succeeds.

### Company Creation Contract

`POST /companies` should be the single atomic setup action:

1. Verify the company exists in Tally.
2. Create the company for the signed-in user.
3. Select it as the active company.
4. Run the initial master sync for ledgers and stock items.
5. Return the saved company and sync result.

The frontend should not separately pair a local agent, manually trigger setup sync, or save a company before verification.

Expected success shape:

```json
{
  "company": {},
  "sync": {
    "status": "success",
    "last_sync_at": "..."
  }
}
```

Expected errors should be mapped to clear UI messages:

- duplicate company
- cannot connect to Tally
- company not found in Tally
- session expired
- unknown backend error

### Tally Sync

- Do not show "Sync masters" or "Refresh Tally data" as a normal primary workflow.
- Sync should happen automatically:
  - after company setup
  - before processing uploaded Excel
  - before commit if cached masters are stale
- If sync fails, show a simple error and allow retry of the failed user action.

### Excel Import

- User can upload an Excel sales file for the active company.
- On upload, backend should:
  1. run a quick master sync
  2. parse the Excel
  3. validate rows
  4. return preview results
- Frontend should show parsed rows and row-level validation errors.
- Frontend should show enough preview detail for approval:
  - row number
  - product name
  - price
  - payment mode
  - voucher date
  - ready/error status
  - error message when invalid
- Do not show raw XML or raw voucher JSON by default.

### Commit

- Commit must require explicit user approval after preview.
- Commit all valid rows when the user clicks commit.
- Invalid rows should remain visible with row-level errors.
- Before commit, backend should verify Tally connection and active company reachability.
- If Tally is unreachable, fail gracefully before posting rows where possible.
- After commit, show a summary:
  - successful commit count
  - failed commit count
  - failed row errors
- Do not implement retry failed rows in this MVP.

### Duplicate Rows

- Duplicate-looking sales rows must be allowed.
- Same product, date, price, and payment mode can represent multiple real sales.
- Do not block duplicates in preview or commit for this MVP.
- If duplicate protection is needed later, it should rely on an explicit transaction ID from the Excel source.

## Required Backend Support For Frontend

- `GET /tally/status` or equivalent backend endpoint for user-facing Tally connection status.
- `GET /companies` should return saved companies and enough information to determine active company.
- `POST /companies` should perform atomic verify/create/select/initial-sync.
- `POST /companies/{company_id}/select` should persist active company.
- Excel upload endpoint should trigger sync-before-validate behavior.
- Commit endpoint should perform pre-commit Tally reachability checks.
- Backend should hide connector internals from frontend responses unless needed for debugging.

## Non-Goals For This Frontend MVP

- No local connector installer flow.
- No local connector pairing token UI.
- No user-facing local connector URL configuration.
- No raw Tally XML display.
- No row selection for commit.
- No retry failed rows UI.
- No duplicate blocking.
