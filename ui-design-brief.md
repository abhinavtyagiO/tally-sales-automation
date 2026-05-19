# Design Brief: AccountPilot

## Visual Identity
AccountPilot employs a professional, trustworthy SaaS aesthetic designed for small business owners. The interface prioritizes clarity and data readability over decorative elements.

### Brand Personality
- **Trustworthy:** Stable, financial-grade feel.
- **Accessible:** Plain-language updates for non-technical users.
- **Efficient:** High-density data views for quick review and action.

## Design System Tokens

### Color Palette
- **Primary:** Corporate Navy (#0f172a) used for sidebar backgrounds and primary actions.
- **Surface:** Neutral whites and light grays (#f7f9fb, #ffffff) for card backgrounds and page surfaces.
- **Success:** Green for "Valid" statuses and successful syncs.
- **Error:** Red for critical mapping errors and failed syncs.
- **Warning:** Yellow/Orange for warnings or items requiring manual review.

### Typography
- **Typeface:** Inter (Sans-serif)
- **Hierarchy:** Strong contrast between headlines and body text to guide the eye through multi-step workflows.

### Components & Patterns
- **Layout:** Standardized two-pane layout with a persistent sidebar for navigation and a main content area for tasks.
- **Cards:** Rounded (8px) card-based architecture to group logical sections.
- **Tables:** High-density, readable tables with inline status badges and action buttons.
- **Status Indicators:** Color-coded badges for immediate visual feedback on data validity.

## Key UX Principles
1. **Always show before committing:** A "Review & Commit" stage ensures transparency before data is sent to Tally.
2. **Never hide errors:** Validation errors should be visible in plain language, but the UI should only expose actions the backend actually supports.
3. **Wizard-like flow:** A guided, step-by-step process (Setup > Dashboard > Upload > Preview/Commit > History) reduces cognitive load for non-technical users.
4. **Real data only:** Dashboard metrics and history must be derived from real backend data. Do not show placeholder financial, cloud, notification, or usage metrics.
5. **Desktop-first:** This MVP is optimized for desktop spreadsheet workflows. Do not spend this phase on mobile navigation or responsive redesign.

## Screen Inventory
- **First-Run Setup:** Shown when a user has no companies. Includes Tally connection status, company name input/dropdown when available, and an Add Company action. Upload controls are hidden until a company exists.
- **Dashboard:** Shown after at least one company exists. Includes Tally connection status, active company card with company switcher, Upload Excel quick action, real vouchers-created metric, and recent imports/activity.
- **Upload Page:** Large file-picker component for `.xlsx` and `.xls` files only. Do not mention drag-and-drop. Include upload guidelines that match the backend contract.
- **Preview and Commit:** Single combined screen after upload. Shows summary cards, validation table, error messages, and commit action. If some rows are invalid, allow committing valid rows with explicit skipped-row warning.
- **History/Logs:** User-readable audit trail for imports and commits. Include filename, upload/commit time, row counts, status, success/failure counts, failed row messages, and voucher IDs/numbers when available. Do not show raw technical logs.

## Navigation
- Sidebar includes: Dashboard, Upload, History/Logs.
- Sidebar primary action is `Upload Excel`, not `New Invoice`.
- Omit Sync Settings for this phase.
- Top header includes page title, active company when selected, last synced text when available, refresh/check connection action, and top-right user initials/email with sign-out.
- Do not include dead notification bells, cloud usage controls, or decorative actions.

## First-Run Setup
- If the authenticated user has no companies, route them to the setup screen.
- Show a simple Tally connection status.
- Let the user provide/select a Tally company name.
- Once company creation succeeds, switch to Dashboard.

## Dashboard Requirements
- Active company card replaces the Stitch Cloud Usage card.
- If multiple companies exist, allow switching active company from the active company card.
- Use existing endpoints only for now:
  - `/companies`
  - `/tally/status`
  - `/companies/{company_id}/imports`
  - `/companies/{company_id}/imports/{import_id}` when details are needed.
- Show Vouchers Created only from real committed rows.
- Do not show fake deltas, fake error counts, fake sync times, cloud plan usage, or placeholder activity.

## Upload Requirements
- Supported file types shown in UI: `.xlsx`, `.xls`.
- Required columns shown in guidelines:
  - `product_name`
  - `price`
  - `payment_mode`
  - `voucher_date`
- Guidelines should explain:
  - product names must exactly match Tally stock items
  - each row becomes one sales voucher
  - voucher date must be valid
- The upload component should be visually prominent, but only use file picker behavior.
- If Tally is disconnected, allow choosing a file but block processing with clear copy.

## Preview and Commit Requirements
- Use one screen for preview and commit.
- Compute frontend summary from preview rows:
  - total rows
  - valid rows
  - error rows
  - ready percentage
  - total amount from valid rows
  - date range from valid rows
- Validation table columns:
  - row/source row
  - product name
  - price
  - payment mode
  - voucher date
  - status
  - error
- Do not show unsupported resolution controls:
  - no Auto-Map
  - no Create New Item
  - no Search Tally Stock
  - no Resolve controls
  - no editable Tally stock or ledger dropdowns
- If invalid rows exist, allow committing valid rows and clearly state how many rows will be skipped.
- After commit, show a compact success/failure summary first, with row-level details below.
- Show Tally voucher number/ID after commit when available.

## History Requirements
- Keep History/Logs as a real MVP screen.
- Use user-readable import and row status, not raw backend logs.
- Include import status such as processed, committed, failed, or partial when derivable.
- Include row-level failed messages and voucher identifiers where available.

## Branding Scope
- Change frontend-visible product text to `AccountPilot`.
- Do not rename backend packages, database files, or internal module names in this phase.

## Source of Truth
- Use the Stitch screenshots as layout and interaction hierarchy reference.
- Use `DESIGN.md` tokens for colors, typography, radius, spacing, and component styling.
- If they differ, follow screenshot UX structure while normalizing visual details to the token system.

## Deferred Backlog
- Dashboard summary backend endpoint, e.g. `GET /companies/{company_id}/dashboard`.
- Sync Settings screen.
- Stock item resolution/mapping UI.
- Auto-map/fuzzy matching.
- Create stock item flow.
- CSV support.
- Drag-and-drop upload.
- Mobile/responsive redesign.
- Notification bell behavior.
- Cloud usage/plan cards.
- Manual invoice creation.
- Raw technical logs in frontend.
