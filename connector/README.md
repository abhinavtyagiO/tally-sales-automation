# AccountPilot Helper

AccountPilot Helper is the Windows-side connector for production Tally access. It runs on the machine where Tally is available, polls the AccountPilot backend over outbound HTTPS, executes Tally operations locally, and posts results back to the backend.

## Runtime Environment

Required variables:

```env
ACCOUNTPILOT_BACKEND_URL=https://api.your-domain.com
ACCOUNTPILOT_AGENT_ID=replace-with-agent-id
ACCOUNTPILOT_AGENT_TOKEN=replace-with-agent-auth-token
TALLY_URL=http://127.0.0.1:9000
```

## Local Run

```bash
python -m connector.main --once
python -m connector.helper_app
```

## First-Run Pairing

AccountPilot Helper can register itself with a setup token created by the web app:

```powershell
AccountPilotHelper.exe --backend-url "https://api.your-domain.com" --setup-token "one-time-token"
```

On success it saves its polling credentials to:

```text
%LOCALAPPDATA%\AccountPilot Helper\config.json
```

Runtime logs are written to:

```text
%LOCALAPPDATA%\AccountPilot Helper\logs\helper.log
```

## Windows Build

On Windows:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\connector\packaging\build_windows.ps1
```

This produces:

```text
connector\dist\AccountPilotHelper.exe
```

Use Inno Setup with `connector\packaging\AccountPilotHelper.iss` to produce:

```text
connector\dist\AccountPilotHelperSetup.exe
```

The installer adds AccountPilot Helper to the current user's Windows startup list.

## Current MVP Limitations

- Browser downloads do not pass URL query parameters to an `.exe` when the user launches it later. A hosted download endpoint or custom launch flow must pass `/SETUP_TOKEN=...` and `/BACKEND_URL=...` to the installer for fully automatic web-to-installer handoff.
- The executable and installer are not code-signed yet.
- Auto-update and crash reporting are not included yet.
- The UI is a minimal status window, not a tray app.
