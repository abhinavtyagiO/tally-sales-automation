## Problem Statement

AccountPilot currently works end to end in local development, but production Tally connectivity is not yet product-ready for normal Tally Desktop users. A pure cloud web app cannot reliably or securely reach a user's local Tally server, and users should not be asked to configure localhost URLs, expose local ports, run manual tunnels, or understand connector architecture.

The user needs AccountPilot to feel like a web product with one simple Tally setup step: sign in, install a small Windows helper on the Tally machine, keep Tally open, and continue company setup. The helper should run in the background, auto-start, auto-connect, and enable the existing Excel upload and commit workflow without making users manage technical infrastructure.

## Solution

Build a production connector model where the AccountPilot web app remains the primary product experience and a lightweight Windows connector runs beside Tally. The connector should communicate with the cloud backend using outbound HTTPS only, preferably long polling, and should execute Tally operations locally against the user's Tally HTTP endpoint.

From the user's perspective, onboarding should prompt first-time users to install AccountPilot Helper, not a technical connector. Once installed, the Helper auto-starts, registers or pairs with the user's AccountPilot account, reports Tally health, and allows the existing company setup flow to proceed. The user should not need to understand polling, ports, local agents, tunnels, or pairing tokens.

For operational flows such as committing valid Excel rows, the frontend should expose one command: commit rows. Under the hood, the backend creates durable connector jobs, the connector leases and executes those jobs through Tally, and the frontend shows progress until the result summary is available.

## User Stories

1. As a first-time AccountPilot user, I want to sign in and be guided to install the required Windows helper, so that I can connect AccountPilot to Tally without understanding technical setup.
2. As a first-time AccountPilot user, I want the helper to be described as AccountPilot Helper, so that the setup feels like part of the product rather than a separate infrastructure component.
3. As a Tally user, I want to install the helper on the computer where Tally is installed, so that AccountPilot can work with my local Tally data.
4. As a Tally user, I want the helper to auto-start when Windows starts, so that I do not need to remember to launch it before using AccountPilot.
5. As a Tally user, I want the helper to auto-connect after installation, so that onboarding continues without manual token entry or connector configuration.
6. As a Tally user, I want AccountPilot to tell me when Tally is not open or not reachable, so that I know what to fix before company setup.
7. As a Tally user, I want AccountPilot to proceed to company setup after the helper and Tally are connected, so that the existing setup flow remains simple.
8. As a Tally user, I want to select or validate my Tally company from the web app, so that I can complete setup without switching into technical connector screens.
9. As a Tally user, I want the helper to keep working quietly in the background, so that I can use AccountPilot once or twice a day without thinking about the helper.
10. As a Tally user, I want the web app to show connection status, so that I know whether AccountPilot can currently reach Tally.
11. As a Tally user, I want clear status messages when the helper is offline, so that I understand why Tally actions cannot proceed.
12. As a Tally user, I want clear status messages when the helper is online but Tally is closed, so that I know to open Tally.
13. As a Tally user, I want to upload Excel in the web app, so that AccountPilot remains a browser-based workflow.
14. As a Tally user, I want to click one Commit rows button, so that voucher creation feels like a single command.
15. As a Tally user, I want to see progress after committing rows, so that I am not left waiting on a hanging request.
16. As a Tally user, I want to see the result summary automatically after commit completes, so that I know how many vouchers were created and which rows failed.
17. As a Tally user, I want partial failures to be reported clearly, so that I can correct only the affected rows or settings.
18. As a Tally user, I want AccountPilot to avoid duplicate vouchers if a network retry happens, so that my Tally books stay clean.
19. As a Tally user, I want AccountPilot to queue work when the helper is temporarily offline, so that I can recover without restarting the whole upload flow.
20. As a Tally user, I want AccountPilot to continue using company-scoped data, so that actions for one company do not affect another company.
21. As a returning AccountPilot user, I want the helper connection to be remembered securely, so that I do not need to pair again every day.
22. As a returning AccountPilot user, I want the helper to reconnect after network interruptions, so that short connectivity problems do not block my work permanently.
23. As a returning AccountPilot user, I want the web app to detect whether the helper is already active, so that I am not repeatedly asked to install it.
24. As a support operator, I want the helper to report health and last-seen information, so that I can diagnose user setup issues.
25. As a support operator, I want errors to distinguish helper offline, Tally unreachable, Tally rejection, and backend validation failures, so that troubleshooting is efficient.
26. As a developer, I want the connector to use outbound HTTPS only, so that users do not need port forwarding, tunnels, or public local URLs.
27. As a developer, I want the backend to own Excel parsing, validation, voucher payload generation, retries, idempotency, and audit logs, so that business behavior stays centralized and testable.
28. As a developer, I want the connector to remain thin, so that the Windows helper has a small responsibility surface and is easier to package.
29. As a developer, I want a direct connector mode to remain available for local development, so that existing development workflows stay fast.
30. As a developer, I want production connector communication to use durable jobs, so that browser requests do not hang while Tally operations run.
31. As a developer, I want health check and company listing to move to the polling model first, so that the risky voucher commit flow is not converted before the protocol is proven.
32. As a developer, I want commit jobs to have idempotency or source fingerprints, so that retrying failed or expired jobs does not create duplicate Tally vouchers.
33. As a product owner, I want the first production connector release to be lightweight, so that we can validate the architecture before investing in a full desktop app.
34. As a product owner, I want the connector to start inside the current repo while the protocol changes quickly, so that backend and connector changes can be developed together.
35. As a product owner, I want the connector to move to a separate repo later when packaging and release management mature, so that Windows builds can have a dedicated lifecycle.

## Implementation Decisions

- The product direction is web app plus lightweight Windows connector, not a full native Windows app as the primary UI.
- The connector will be user-facing as AccountPilot Helper or AccountPilot for Tally, while internal code may continue using connector terminology.
- The connector should initially live in the current codebase while the backend protocol is still evolving.
- A separate connector repository should be considered once the connector becomes a packaged Windows app with its own installer, release process, auto-update flow, and CI needs.
- The production communication model should be outbound HTTPS from connector to backend, not cloud backend calls to a user's localhost and not browser calls to localhost.
- Long polling is the preferred connector communication pattern: the connector asks for work with a wait timeout, receives either a leased job or no-op, and immediately resumes polling.
- The connector should back off on repeated network failures while remaining quiet and low-load during idle periods.
- The connector will mostly be idle because users are expected to upload and commit Excel files once or twice per day; the protocol should optimize for low operational overhead while still responding quickly when work exists.
- Browser requests should not wait for direct Tally execution. The backend should create a commit run or equivalent durable unit, return quickly, and let the frontend poll for status.
- The frontend should preserve a one-command user experience for commit rows even though execution is async under the hood.
- The backend should own Excel parsing, row validation, master cache decisions, voucher payload generation, job creation, retry policy, status transitions, user-facing errors, idempotency, and database state.
- The connector should own authentication, heartbeat, long polling, local Tally health checks, local Tally XML execution, result submission, and minimal local status reporting.
- The connector must not own Excel parsing, product validation, voucher business rules, retry decisions, user workflow state, or product database state.
- Add a durable connector job model with states such as queued, leased, completed, failed, expired, and cancelled.
- Add connector-facing backend APIs for registration or setup-session exchange, heartbeat, long polling, and job result submission.
- Add frontend-visible status APIs for helper connection state, Tally connection state, job progress, commit run progress, and final summaries.
- Introduce a setup-session or equivalent short-lived onboarding token so the web app can initiate connector installation/registration without exposing manual pairing tokens to normal users.
- Store connector credentials securely on Windows, ideally using Windows Credential Manager when packaging begins.
- The connector should auto-start on Windows login.
- The connector should have a minimal tray or status surface showing AccountPilot connection, Tally connection, and last sync or last activity.
- Advanced troubleshooting may expose Tally URL, logs, reconnect, and sign out; normal onboarding should not expose local agent, pairing token, localhost, port, tunnel, or relay language.
- Convert Tally operations gradually: start with health check and list companies, then company validation and master sync, then voucher commit after idempotency is designed.
- Keep direct mode available for local development while production polling mode is introduced.
- Commit flow should be modeled as one frontend command with backend-managed progress and final summary.
- Voucher creation jobs require idempotency keys or source fingerprints before retry behavior is enabled.
- Job leasing should include lease expiration so abandoned connector work can be recovered safely.
- Job result handling should update company, import, import row, voucher log, and commit summary state through backend-owned handlers.
- The onboarding state model should include states for helper required, waiting for helper, helper connected, Tally not open, Tally connected, select company, company validated, and ready.

## Testing Decisions

- Tests should focus on external behavior and state transitions rather than implementation details of polling loops.
- Backend connector job tests should verify job creation, leasing, lease expiration, result submission, failure handling, and status transitions.
- Backend auth tests should verify that connector registration, heartbeat, polling, and result submission require valid connector credentials.
- Backend company-scoping tests should verify that connectors can only receive jobs for the correct user, company, or registered agent context.
- Backend result-handler tests should verify that health check, company listing, company validation, master sync, ledger creation, and voucher creation results update product state correctly.
- Commit-flow tests should verify that one commit request creates durable work, reports progress, and returns the same final summary shape expected by the frontend.
- Idempotency tests should verify that retried voucher jobs do not create duplicate successful voucher records or duplicate Tally execution requests when the backend can determine a prior completion.
- Frontend tests should verify onboarding states, helper-required messaging, waiting-for-helper messaging, Tally-not-open messaging, connected state, commit progress, and final summary rendering.
- Connector unit tests should verify polling behavior, backoff behavior, job dispatch routing, local Tally error normalization, result submission, and credential handling through test doubles.
- Connector integration tests should use a fake backend and fake Tally service to verify end-to-end connector behavior without requiring a real Tally instance.
- Existing backend unittest coverage and frontend derivation tests are prior art for stateful product behavior.
- Existing parent flow tests are prior art for company-scoped upload, validation, commit, and voucher log behavior.
- Existing frontend derivation tests are prior art for testing user-visible derived state without coupling to UI implementation details.

## Out of Scope

- Building a full native Windows application as the primary AccountPilot UI.
- Requiring users to configure port forwarding, ngrok, tunnels, or public connector URLs.
- Browser-to-localhost Tally or browser-to-localhost connector communication for production.
- Manual file export/import fallback as the primary workflow.
- Auto-creating Tally stock items.
- Changing the Excel upload contract beyond what is needed for async connector execution.
- Reworking Google login or company ownership semantics.
- Implementing advanced auto-update, signed installer, crash reporting, or enterprise deployment tooling in the first tracer-bullet release.
- Moving the connector into a separate repository before the backend protocol stabilizes.
- Converting all Tally operations in one large release without first proving health and company-listing jobs.

## Further Notes

The major product principle is that the connector should be technically necessary but not experientially prominent. Normal users should experience it as installing AccountPilot Helper once during onboarding. The existing company setup and Excel upload workflows should remain browser-led.

The major architecture principle is that the connector is dumb and the backend is smart. This keeps accounting behavior, validation, idempotency, auditability, and user-facing status centralized in the cloud backend while allowing the connector to do the one thing the cloud cannot do directly: safely reach local Tally.

The recommended first tracer bullet is to add the connector job protocol and move health check plus Tally company listing onto long polling. Voucher commit should be converted only after the job model, result handling, and idempotency approach are proven.
