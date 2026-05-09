# PRD: Frontend MVP With Backend-Managed Tally Connection

## Problem Statement

Users need a smooth web experience for importing sales Excel files into Tally without understanding the technical machinery required to reach Tally. The current prototype exposes implementation details such as local-agent pairing, manual sync, and local development login. This creates confusion, makes the product feel technical, and does not match the intended architecture where the local connector is a trusted Tally connector managed by the backend.

The user should be able to sign in with Google, select or add a Tally company, upload an Excel file, review row-level validation results, and explicitly commit valid vouchers to Tally. The product should hide connector setup, pairing tokens, sync internals, local URLs, and raw Tally details. When Tally is unavailable, the UI should communicate that simply and directly.

## Solution

Build a Next.js frontend and adjust supporting backend contracts so the web app presents a simple Tally Sales Automation workflow:

1. User signs in with real Google OAuth.
2. User lands on an authenticated dashboard.
3. Dashboard shows a simple Tally connection state.
4. User adds one or more Tally companies.
5. Company creation is a single backend action that verifies the company in Tally, saves it, selects it as active, and performs initial master sync.
6. User selects an active company.
7. User uploads an Excel sales file.
8. Backend runs a quick master sync, parses the Excel, validates rows, and returns a preview.
9. User reviews the preview and explicitly commits all valid rows.
10. Frontend shows a success/failure summary after commit.

The frontend must use backend APIs only for product workflows. It must not call the local connector directly. The local connector remains an internal, trusted Tally connector used by the backend to communicate with Tally.

## User Stories

1. As a business user, I want to sign in with Google, so that I do not need to manage another password.
2. As a business user, I want the sign-in screen to show a real Google sign-in button, so that I trust the authentication flow.
3. As a business user, I want to stay signed in after refreshing the page, so that I can continue work without repeating login.
4. As a business user, I want to sign out, so that I can end my session on a shared machine.
5. As a business user, I want sign-out to fully end my backend session, so that old cookies cannot keep using my account.
6. As a business user, I want to see my signed-in identity, so that I know which account I am using.
7. As a business user, I want a clear message if Google sign-in is not configured, so that I am not shown a fake or broken login.
8. As a developer, I want local-dev login hidden behind explicit environment flags, so that fake login cannot accidentally ship.
9. As a developer, I want the backend to reject test login tokens unless dev auth is enabled, so that production auth remains safe.
10. As a business user, I want to see whether Tally is reachable, so that I understand whether Tally actions can run.
11. As a business user, I want Tally connection errors to be phrased simply, so that I am not asked to understand agents, ports, URLs, or pairing.
12. As a business user, I want the dashboard to avoid connector jargon, so that the product feels like a normal business tool.
13. As a business user, I want to add a Tally company, so that I can import sales for that company.
14. As a business user, I want to add more than one Tally company, so that I can work across my Tally companies from one account.
15. As a business user, I want to select an active company, so that subsequent uploads and commits target the correct company.
16. As a business user, I want my active company selection to persist, so that I do not need to reselect it after refreshing or returning.
17. As a business user, I want the app to list companies from Tally when possible, so that I can avoid typos.
18. As a business user, I want to type the company name when a list is unavailable, so that I can still continue setup.
19. As a business user, I want company creation to verify the company exists in Tally before saving, so that typos do not create unusable companies.
20. As a business user, I want duplicate company names blocked, so that my company list stays clean.
21. As a business user, I want a new company to become active after setup, so that I can immediately work with it.
22. As a business user, I want the app to prepare Tally data after company setup, so that I do not need to understand master sync.
23. As a business user, I do not want to see a "Sync masters" button in the normal flow, so that I am not exposed to implementation concepts.
24. As a business user, I want upload to handle any needed Tally refresh automatically, so that the import flow feels simple.
25. As a business user, I want to upload an Excel sales file for the active company, so that the app can prepare vouchers.
26. As a business user, I want the app to parse my Excel file and show the rows, so that I can confirm the data was read correctly.
27. As a business user, I want row-level validation errors, so that I know exactly which rows need correction.
28. As a business user, I want valid rows clearly marked as ready, so that I know what will be committed.
29. As a business user, I want invalid rows to remain visible, so that I can understand why they will not be posted.
30. As a business user, I want the preview table to show row number, product name, price, payment mode, voucher date, status, and error, so that I can approve the import efficiently.
31. As a business user, I do not want to see raw XML or raw voucher JSON, so that the screen stays understandable.
32. As a business user, I want to explicitly approve commit after preview, so that vouchers are not posted before I review them.
33. As a business user, I want all valid rows committed together, so that I do not need row-selection controls in the MVP.
34. As a business user, I want duplicate-looking sales rows allowed, so that multiple sales of the same item on the same day can be posted.
35. As a business user, I want commit to check Tally reachability before posting, so that failures are clear and partial posting risk is reduced.
36. As a business user, I want a commit summary, so that I know how many rows succeeded and failed.
37. As a business user, I want failed row errors after commit, so that I can understand what went wrong.
38. As a business user, I do not need retry-failed-rows controls in the MVP, so that the interface stays focused.
39. As an operator, I want the backend to hide local connector details from normal frontend responses, so that users are not exposed to implementation internals.
40. As a developer, I want backend Tally status to distinguish internal causes while returning simple user-facing messages, so that the UI stays clean and logs remain useful.
41. As a developer, I want auth, company setup, Tally status, import, validation, and commit behavior covered by tests, so that frontend-facing contracts do not regress.
42. As a developer, I want the frontend split into focused modules, so that login, company setup, import, and commit flows can evolve without one large page component.

## Implementation Decisions

- The frontend will be built with Next.js and will remain the web product entry point.
- The frontend will call backend APIs only for product workflows.
- The frontend will not call the local connector directly, including for health checks.
- User-facing language will use "Tally" or "Tally connection" and avoid "agent", "local agent", "connector setup", and "pairing".
- Google OAuth will use Google Identity Services on the frontend.
- The frontend will require `NEXT_PUBLIC_GOOGLE_CLIENT_ID` for normal login.
- The backend will require `GOOGLE_CLIENT_ID` to verify real Google ID tokens.
- Local-dev login will be hidden unless `NEXT_PUBLIC_ENABLE_DEV_LOGIN=true`.
- Backend test-token login will be rejected unless `ALLOW_DEV_AUTH=true`.
- Backend sessions will continue to use HttpOnly cookies.
- Authenticated frontend requests will use `credentials: "include"`.
- Logout will revoke the server-side session and clear frontend state.
- A backend Tally status endpoint will be added for frontend use.
- The Tally status endpoint will return simple user-facing states such as connected and cannot-connect-to-Tally.
- Internally, backend can distinguish connector unavailable, Tally unreachable, company unreachable, and unknown failures.
- Company listing will return enough information for the frontend to determine the active company.
- Company selection will persist per user through the backend.
- Company creation will be a single atomic backend action.
- Company creation will verify the company exists in Tally before saving.
- Company creation will create the company, select it as active, run initial master sync, and return company plus sync result.
- Company creation will block duplicate company names per user.
- Company setup will support a company dropdown when the backend/local connector can list Tally companies reliably.
- Company setup will fall back to typed company name when a company list is unavailable.
- The normal dashboard will not show manual local-agent pairing.
- The normal dashboard will not show "Sync masters" or "Refresh Tally data" as a primary workflow.
- Sync will run automatically after company setup, before Excel processing, and before commit when cached masters are stale.
- Excel upload will trigger backend sync-before-validate behavior.
- Excel upload will return persisted import data and row-level validation results.
- Preview will be table-first and show business fields rather than raw voucher internals.
- Commit will require explicit approval after preview.
- Commit will post all valid rows.
- Commit will not post invalid rows.
- Commit will perform a pre-commit Tally reachability check.
- Commit will return row-level results and aggregate success/failure counts.
- Duplicate-looking sales rows will be allowed in preview and commit.
- Current duplicate blocking based on product/date/price/payment/source fingerprint should be removed from the active MVP import path or bypassed for this flow.
- Retry failed rows will not be implemented in the frontend MVP.
- Deep modules to build or modify:
  - Authentication/session module for real Google token verification and gated dev auth.
  - Tally connection status module with a simple frontend contract and richer internal error mapping.
  - Company setup module that performs verify/create/select/initial-sync atomically.
  - Company selection module that persists active company per user.
  - Import pipeline module that performs sync-before-parse/validate and returns preview rows.
  - Commit orchestration module that checks Tally reachability, commits valid rows, and returns summaries.
  - Frontend API client module for credentialed requests and user-facing error normalization.
  - Frontend UI modules for login, Tally status, company setup/selector, import preview, and commit summary.

## Testing Decisions

- Tests should validate external behavior and contracts, not implementation details.
- Backend tests should cover real Google-token verification behavior through mocked Google responses.
- Backend tests should cover dev auth being rejected by default and allowed only when explicitly enabled.
- Backend tests should cover logout revoking cookie-backed sessions.
- Backend tests should cover Tally status responses for connected, connector unavailable, Tally unreachable, and unknown errors.
- Backend tests should cover atomic company creation: verify company, create company, select active company, run initial sync, and return sync result.
- Backend tests should cover duplicate company rejection.
- Backend tests should cover company-list dropdown support when Tally company listing is available, and typed fallback when it is unavailable.
- Backend tests should cover upload triggering master sync before validation.
- Backend tests should cover row-level preview results for valid and invalid rows.
- Backend tests should cover duplicate-looking rows being allowed.
- Backend tests should cover commit checking Tally reachability before posting.
- Backend tests should cover commit summary counts and failed row errors.
- Frontend tests should cover login configuration states: Google configured, Google missing, dev login enabled, and dev login hidden by default.
- Frontend tests should cover authenticated dashboard load, session failure handling, and sign-out state reset.
- Frontend tests should cover Tally connection status rendering without connector jargon.
- Frontend tests should cover company setup success, duplicate company error, Tally unreachable error, and company-not-found error.
- Frontend tests should cover active company selection and persisted selection behavior.
- Frontend tests should cover Excel upload preview rendering.
- Frontend tests should cover commit approval and commit summary rendering.
- Existing backend unittest coverage provides prior art for route/service-level behavior, mocked Tally responses, company-scoped sync, persisted imports, process, and commit flows.
- Existing frontend build verification should continue to run with `pnpm run build`.

## Out of Scope

- Local connector installer, updater, or startup management.
- Local connector pairing token UI.
- User-facing local connector URL configuration.
- Browser-to-local-connector product workflows.
- Raw Tally XML display.
- Raw voucher JSON preview by default.
- Row selection for commit.
- Retry failed rows UI.
- Duplicate blocking based on same product/date/price/payment.
- GST handling or tax ledger splitting.
- Multi-item invoices.
- Customer-level party tracking.
- Bank reconciliation.
- Cost centers.
- Automatic stock item creation.
- Fuzzy product matching.
- Organization/team accounts.
- Password login.

## Further Notes

- The local connector remains essential, but it should be operationally invisible to the user. The product should feel like it connects to Tally, not like it asks the user to manage a technical bridge.
- The current prototype already contains useful backend primitives for users, sessions, companies, local connector operations, imports, import rows, and voucher logs. This PRD intentionally changes the user-facing contract and flow rather than discarding all existing backend work.
- The README still describes an operator flow with explicit local-agent pairing and manual sync. Documentation should be updated after implementation to match the new product flow.
- The existing duplicate-detection behavior conflicts with the clarified product requirement that repeated same-item sales are valid. Implementation should ensure the frontend MVP import path allows those rows.
- Company setup should optimize for a dropdown when Tally company listing is available, but typed verified input remains an acceptable MVP fallback.

## Implementation Status

Completed in this implementation pass:

- Real Google OAuth remains the default login path, while local-dev login is hidden behind `NEXT_PUBLIC_ENABLE_DEV_LOGIN=true` and backend `ALLOW_DEV_AUTH=true`.
- Backend dev auth is rejected by default and cookie-backed logout revokes the server-side session.
- Backend-owned Tally status and Tally company discovery endpoints were added so the frontend does not call the local connector directly.
- Company listing now returns active company state, and company selection persists per user.
- Company creation now verifies the company through backend-managed Tally connectivity, rejects duplicates, selects the new company, and runs initial master sync.
- Excel upload now runs a master sync before parsing/validation and returns row-level preview data.
- Commit now requires explicit frontend approval, checks Tally reachability, posts valid rows, and returns success/failure summary details.
- Duplicate-looking sales rows are allowed in the active import path.
- Frontend was replaced with focused modules for login, Tally status, company setup/selection, import preview, and commit summary.
- User-facing errors were normalized to avoid exposing local-agent, pairing, port, raw XML, or raw JSON concepts.
- README documentation was updated to describe the new product flow.

Verification completed:

- Backend unittest suite passes.
- Next.js production build passes.
