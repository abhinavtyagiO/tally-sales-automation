# PRD: AccountPilot Frontend Redesign

## Problem Statement

The current frontend proves the end-to-end Tally sales import workflow, but it is still a prototype interface. It compresses setup, company management, upload, preview, commit, and result review into one screen, which makes the product harder to understand for non-technical users. The UI also does not yet reflect the new AccountPilot brand or the Stitch design direction.

Users need a clear, trustworthy desktop workflow that helps them connect their Tally company, upload Excel sales rows, validate the data, review the impact, commit valid vouchers to Tally, and inspect past activity without seeing technical connector details or unsupported actions.

## Solution

Redesign the frontend as a desktop-first AccountPilot application using the Stitch screenshots as the layout and interaction reference and the Stitch design tokens as the visual system. The redesign will keep the existing backend behavior and endpoints, but reorganize the UI into clear views:

- First-run setup when no company exists.
- Dashboard after a company exists.
- Upload Excel view.
- Combined preview and commit view.
- History/Logs view.

The application will show only real backend-derived data. It will not include dead controls, fake metrics, raw technical logs, Sync Settings, stock item resolution controls, or unsupported creation/mapping actions. AccountPilot will remain a frontend-visible brand change only; internal backend/module names are not renamed in this phase.

## User Stories

1. As a new AccountPilot user, I want to sign in with Google, so that my companies and imports are tied to my account.
2. As a new AccountPilot user, I want to see a first-run setup screen when I have no companies, so that I know the next step is connecting a Tally company.
3. As a new AccountPilot user, I want to see whether Tally is connected during setup, so that I know whether company setup can work.
4. As a new AccountPilot user, I want to type a Tally company name when company discovery is unavailable, so that I can still continue setup.
5. As a new AccountPilot user, I want to pick a Tally company from a discovered list when available, so that setup is easier and less error-prone.
6. As a new AccountPilot user, I want AccountPilot to verify my company in Tally before saving it, so that invalid companies are not added.
7. As a new AccountPilot user, I want to land on the dashboard after adding my first company, so that I can start using the product.
8. As a returning AccountPilot user, I want to land on the dashboard when I already have a company, so that I can quickly assess current status.
9. As a returning AccountPilot user, I want to see my active company on the dashboard, so that I know which Tally company actions will affect.
10. As a multi-company user, I want to switch active company from the dashboard, so that upload and history views operate on the correct company.
11. As a user, I want to see Tally connection status on the dashboard, so that I know whether AccountPilot can sync and commit.
12. As a user, I want to manually refresh/check the Tally connection, so that I can recover after opening Tally or fixing connectivity.
13. As a user, I want dashboard metrics to be based on real data, so that I can trust the product.
14. As a user, I want to see a real vouchers-created count, so that I understand the amount of work AccountPilot has completed.
15. As a user, I want to see recent imports on the dashboard, so that I can quickly inspect the latest activity.
16. As a user, I want the sidebar to show Dashboard, Upload, and History/Logs only, so that navigation stays focused.
17. As a user, I want the primary sidebar action to say Upload Excel, so that it matches the actual workflow.
18. As a user, I want sign out available in the top-right user area, so that account control is easy to find but not distracting.
19. As a user, I want the top header to show the current page title, so that I understand where I am.
20. As a user, I want the top header to show active company context when available, so that I do not accidentally upload to the wrong company.
21. As a user, I want the top header to show last sync information when available, so that I can judge freshness.
22. As a user, I want the upload page to focus on selecting an Excel file, so that the import flow is obvious.
23. As a user, I want the upload component to be large and prominent, so that I know exactly where to start.
24. As a user, I want upload copy to avoid drag-and-drop claims, so that the UI does not promise unsupported behavior.
25. As a user, I want the upload page to show only `.xlsx` and `.xls` support, so that I do not try unsupported CSV files.
26. As a user, I want upload guidelines to list the exact required columns, so that I can format my spreadsheet correctly.
27. As a user, I want upload guidelines to explain that product names must exactly match Tally stock items, so that validation errors are understandable.
28. As a user, I want upload guidelines to explain that each row becomes one sales voucher, so that I understand the import effect.
29. As a user, I want upload guidelines to explain that voucher dates must be valid, so that date errors are avoidable.
30. As a user, I want to select a file even if Tally is disconnected, so that I can prepare the upload.
31. As a user, I want processing to be blocked when Tally is disconnected, so that I do not start a workflow that must fail.
32. As a user, I want a clear disconnected-state message, so that I know to open Tally or check connectivity.
33. As a user, I want upload to trigger backend master sync and validation, so that the preview reflects current Tally data.
34. As a user, I want upload errors to be shown in plain language, so that I can correct issues without reading logs.
35. As a user, I want a preview screen after upload, so that I can inspect data before committing to Tally.
36. As a user, I want the preview and commit action on one screen, so that I do not navigate through unnecessary steps.
37. As a user, I want summary cards for total rows, valid rows, errors, ready percentage, amount, and date range, so that I can understand the batch at a glance.
38. As a user, I want summary values to be computed from preview rows, so that the numbers reflect exactly what will be committed.
39. As a user, I want a validation table with row number, product name, price, payment mode, voucher date, status, and error, so that I can review each row.
40. As a user, I want invalid product rows to show a clear product-not-found error, so that I know the row cannot be committed.
41. As a user, I want missing ledgers not to block preview when the backend can create configured ledgers at commit time, so that valid rows are not falsely marked as errors.
42. As a user, I want unsupported stock item creation controls hidden, so that I am not offered actions the product cannot perform.
43. As a user, I want unsupported auto-map controls hidden, so that I am not misled into expecting fuzzy matching.
44. As a user, I want unsupported Tally stock search and resolve controls hidden, so that the interface matches real backend behavior.
45. As a user, I want to commit valid rows even when some rows are invalid, so that one bad row does not block the whole file.
46. As a user, I want the commit button to say how many valid rows will be committed, so that the action is explicit.
47. As a user, I want the UI to warn me when invalid rows will be skipped, so that I understand partial commits.
48. As a user, I want a final commit action that clearly states it will push vouchers to Tally, so that I treat it as a serious accounting action.
49. As a user, I want the commit screen to show total valid amount and date range, so that I can verify the batch before pushing.
50. As a user, I want commit progress to be visible, so that I know the app is working while vouchers are sent to Tally.
51. As a user, I want a compact success summary after commit, so that I can immediately confirm the outcome.
52. As a user, I want failed commit rows summarized after commit, so that I know what still needs attention.
53. As a user, I want row-level commit statuses below the summary, so that I can audit each row.
54. As a user, I want Tally voucher numbers or IDs shown when available, so that I can reconcile AccountPilot with Tally.
55. As a user, I want duplicate-looking rows to remain allowed, so that repeated sales of the same item can be committed.
56. As a user, I want missing configured ledgers to be created during commit, so that ordinary payment modes can work without manual setup.
57. As a user, I want stock items not to be auto-created, so that the Tally stock list remains controlled.
58. As a user, I want a History/Logs screen, so that I can review past uploads and commits.
59. As a user, I want History/Logs to show filenames, upload time, row counts, and statuses, so that I can identify prior batches.
60. As a user, I want History/Logs to show success and failure counts after commit, so that I can assess batch outcomes.
61. As a user, I want History/Logs to show failed row messages, so that I can understand what went wrong.
62. As a user, I want History/Logs to show voucher identifiers when available, so that I can reconcile with Tally later.
63. As a user, I do not want to see raw technical logs in the frontend, so that I am not overwhelmed by implementation details.
64. As a non-technical user, I want all connector details hidden, so that AccountPilot feels like a simple Tally connection workflow.
65. As a non-technical user, I want plain-language status messages, so that I understand whether I can upload or commit.
66. As a user, I want the app name to be AccountPilot everywhere visible, so that the product branding is consistent.
67. As a developer, I want the internal backend package names left unchanged, so that the redesign does not create unnecessary code churn.
68. As a developer, I want UI views split into testable modules, so that dashboard metrics and preview summaries can be verified independently.
69. As a developer, I want dashboard metrics computed from existing endpoints for now, so that the redesign does not require backend API expansion.
70. As a developer, I want a deferred backlog for intentionally omitted features, so that future work is tracked without polluting the MVP UI.

## Implementation Decisions

- The frontend will be reorganized into internal views for setup, dashboard, upload, preview/commit, and history/logs.
- Real Next.js routing is not required for this phase; view-state navigation inside the existing app is acceptable.
- The visible brand becomes AccountPilot across frontend-visible labels, metadata, login, sidebar, and headers.
- Internal backend modules, package names, database file names, and service names are not renamed.
- The UI will use the Stitch screenshots for layout and interaction hierarchy.
- The UI will use the Stitch design tokens for colors, typography, radius, spacing, cards, badges, and table styling.
- The app remains desktop-only for this phase.
- No mobile navigation, mobile table redesign, or responsive sidebar is required.
- The sidebar will include Dashboard, Upload, and History/Logs.
- Sync Settings is omitted from this phase.
- The sidebar primary button says Upload Excel.
- The top header includes page title, active company context when available, last sync text when available, connection refresh/check action, user initials/email, and sign out.
- Notification bells and other decorative dead controls are omitted.
- First-run setup appears when the authenticated user has no companies.
- First-run setup includes Tally status and company name selection/input.
- Upload controls are hidden until at least one company exists.
- Dashboard appears after at least one company exists.
- Dashboard includes Tally connection status, active company card, real vouchers-created metric, Upload Excel quick action, and recent imports.
- The active company card replaces the Stitch Cloud Usage card.
- Multiple company switching happens from the active company card.
- Dashboard metrics use existing endpoints only.
- Vouchers Created is computed from committed import rows.
- Placeholder metrics such as fake deltas, fake errors, average sync time, cloud usage, premium plan usage, and fake activity are not shown.
- Upload page uses a large file-picker component, not drag-and-drop.
- Upload copy supports only `.xlsx` and `.xls`.
- Upload guidelines must match the backend Excel contract.
- Upload guidelines list `product_name`, `price`, `payment_mode`, and `voucher_date`.
- Upload processing is blocked when Tally is disconnected, but file selection can happen.
- Upload continues to use the existing company-scoped import upload endpoint.
- The preview and commit workflow is one screen.
- The preview screen computes totals, valid count, error count, ready percentage, total amount, and date range from returned rows.
- The preview table shows only backend-supported data and actions.
- The UI will not show Auto-Map, Create New Item, Search Tally Stock, Resolve controls, or editable Tally stock/ledger dropdowns.
- Valid rows can be committed even if invalid rows exist.
- The commit CTA states the number of valid rows that will be committed.
- The UI warns when invalid rows will be skipped.
- After commit, a compact success/failure summary appears above row details.
- Voucher numbers or IDs are displayed when available from commit responses or import details.
- History/Logs is user-readable only and does not show raw technical logs.
- History/Logs uses existing import list and import detail endpoints.
- Import status labels should be derived from available import and row statuses.
- Existing backend endpoints remain the data source for this phase.
- A dashboard summary endpoint is deferred to backlog.
- Deep frontend modules should be extracted for view navigation/state, dashboard metric derivation, import preview summary derivation, and response/status formatting.

## Testing Decisions

- Tests should verify external behavior and user-visible state, not implementation details such as component internals or CSS class names.
- Dashboard metric derivation should be tested with committed, processed, empty, and partially failed import data.
- Preview summary derivation should be tested for all-valid, mixed-valid-invalid, all-invalid, and empty/edge cases.
- Commit CTA state should be tested for disconnected Tally, no valid rows, some valid rows, and busy state.
- Company setup routing should be tested for no-company and existing-company states.
- Active company switching should be tested by verifying that subsequent upload/history actions use the selected company.
- Upload file type messaging should be tested to ensure CSV is not advertised.
- History formatting should be tested for processed, committed, failed, and partial imports.
- Error formatting should be tested using current backend error messages for Tally unreachable, company not found, product not found, and upload parse failures.
- Sign-out behavior should be retained and tested from the top-right user control.
- Existing backend tests for auth, company scoping, upload, commit, ledger creation, and voucher creation remain prior art for backend behavior.
- Frontend tests may use lightweight component/unit tests for pure derivation modules first, because the current frontend has limited test coverage.
- Manual browser verification should cover first-run setup, dashboard, upload, preview with valid rows, preview with invalid rows, commit success, and history.

## Out of Scope

- Sync Settings screen.
- Dashboard summary backend endpoint.
- Stock item resolution or mapping UI.
- Auto-map or fuzzy matching.
- Stock item creation in Tally.
- CSV upload support.
- Drag-and-drop upload behavior.
- Mobile or responsive redesign.
- Notification bell behavior.
- Cloud usage or plan cards.
- Manual invoice creation.
- Raw technical logs in frontend.
- Backend package/module/database renaming.
- GST splitting, tax ledger handling, multi-item invoices, party/customer tracking, bank reconciliation, cost centers, organization/team accounts, or password login.

## Further Notes

- The local connector remains trusted product infrastructure and should not appear as a user-managed pairing workflow.
- User-facing language should describe Tally connectivity, not connector internals.
- The redesign should preserve current successful end-to-end behavior: Google login, company setup, Tally connectivity, Excel upload, master sync, validation preview, committing valid rows, configurable ledger creation, voucher creation, and row-level result reporting.
- The product should continue to allow duplicate-looking sales rows because a product can be sold more than once in a day.
- The AccountPilot UI should feel like a financial operations tool: quiet, structured, high-density, and trustworthy.

## Implementation Status

- Completed #16: AccountPilot shell and first-run setup are implemented in the Next frontend. Authenticated users with no companies now see setup, while users with companies enter the main shell.
- Completed #17: Dashboard is implemented with active company context, company switching, real Tally connection status, committed voucher count derived from import details, and recent import activity.
- Completed #18: Upload Excel view is implemented with a large picker, `.xlsx`/`.xls` messaging, backend-contract guidelines, and Tally-disconnected processing protection.
- Completed #19: Preview screen is implemented with computed summary cards and a backend-supported validation table.
- Completed #20: Commit flow is implemented from the preview screen with valid-row commit count, skipped-invalid warning, success/failure summary, row statuses, and voucher identifier display where available.
- Completed #21: History/Logs is implemented as a user-readable import audit screen using existing endpoints and omitting raw technical logs.
- Completed #22: Frontend derivation helpers and reusable view components were extracted for summaries, metrics, statuses, voucher IDs, and error formatting. Focused Node tests cover the derivation helpers.
- Completed #23: Desktop visual polish has been applied against the Stitch-inspired AccountPilot direction while removing unsupported/dead UI controls.

## Verification Status

- `cd frontend && pnpm run build` passed with Next.js 16.2.4.
- `cd frontend && pnpm run test:derivations` passed with 5 derivation helper tests.
- `env PYTHONPYCACHEPREFIX=/Users/abhinav/Desktop/tally-sales-automation-mvp/.pycache .venv/bin/python -m unittest discover -s tests` passed with 31 tests.
