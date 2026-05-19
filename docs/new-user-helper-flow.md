# New User Flow With AccountPilot Helper

This document captures the intended first-run user flow for the web app plus Windows Helper architecture.

## 1. User Opens AccountPilot

The user opens the AccountPilot web app and signs in with Google.

The backend creates the user and session. For a first-time user, there are no companies and no connected Helper.

## 2. Web App Shows Helper Setup

The web app prompts the user to install **AccountPilot Helper** on the Windows computer where Tally is installed.

Use user-facing language like:

- AccountPilot Helper
- Tally computer
- Keep Tally open

Avoid normal-user copy like:

- connector
- local agent
- localhost
- port
- polling
- tunnel

## 3. User Installs AccountPilot Helper

The user clicks **Download for Windows**.

Behind the scenes:

1. Web app asks the backend for a short-lived setup session.
2. Helper receives or is given the setup token.
3. Helper registers with the backend.
4. Backend stores Helper identity and credentials.
5. Helper starts polling the backend.

Current MVP note: setup sessions and registration exist, but automatic installer token handoff still needs packaging polish.

## 4. Helper Auto-Connects

After installation, Helper should:

- auto-start on Windows login
- register or reuse stored credentials
- poll the backend over outbound HTTPS
- report heartbeat
- call local or LAN Tally when jobs arrive

The web app detects:

```text
AccountPilot Helper is connected.
```

## 5. Web App Checks Tally

The backend queues a Tally health or company discovery job.

Flow:

```text
Backend creates job
Helper polls backend
Helper receives job
Helper calls Tally
Helper posts result
Web app reads result
```

If Tally is open and reachable, the user sees the Tally company list.

Example:

```text
Bhrama Enterprises
```

If Tally is not reachable, the user sees plain copy:

```text
Open Tally and check the connection, then try again.
```

## 6. User Completes Company Setup

The user selects the Tally company and enters required company details:

- GSTIN
- GST state

The backend validates the company through Helper/Tally and saves it.

## 7. Initial Master Sync

The backend creates connector jobs to sync:

- ledgers
- stock items

Helper executes those jobs against Tally and returns results. The backend stores the company-scoped cache.

## 8. User Reaches Dashboard

After setup, the user lands in the normal app:

- Dashboard
- Inventory
- Upload
- History/Logs

Helper keeps polling quietly in the background.

## 9. User Uploads Excel

The user selects an Excel file in the web app.

Backend:

- parses the Excel file
- validates rows against synced Tally stock items and ledgers
- returns a preview

The user sees valid rows, invalid rows, and row-level errors.

## 10. User Clicks Commit Rows

From the user's perspective, this is one action:

```text
Commit rows
```

Behind the scenes in polling mode:

1. Backend creates a commit run.
2. Backend creates voucher jobs for valid rows.
3. Helper polls and receives voucher jobs.
4. Helper creates vouchers in Tally.
5. Helper posts each result.
6. Backend updates row status and summary.

The user sees progress and then the final result summary.

Example:

```text
5 succeeded, 0 failed
```

## Product Principle

The user should feel like:

```text
Sign in
Install AccountPilot Helper
Select Tally company
Upload Excel
Commit rows
Done
```

They should not feel like they are configuring infrastructure.
