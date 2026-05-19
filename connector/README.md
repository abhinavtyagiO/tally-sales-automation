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

- Credentials are provided through environment variables for the first packaging pass.
- The setup-token handoff from web onboarding to installer is not automated yet.
- The executable and installer are not code-signed yet.
- Auto-update and crash reporting are not included yet.
- The UI is a minimal status window, not a tray app.
