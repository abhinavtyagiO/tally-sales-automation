# Agent Instructions

- Always create and switch to a new feature branch before committing code changes.
- Never commit directly on `main`, `production`, or deployment branches.
- Keep commits scoped to the active task and leave unrelated untracked files untouched.
- If a commit is accidentally made on a protected branch, preserve it on a feature branch first, then restore the protected branch to its remote tracking branch.
- AccountPilot Helper releases are required for changes under `connector/**` and for shared code imported by the helper. In particular, `connector/main.py` packages `backend.services.tally_client`, so changes to `backend/services/tally_client.py` require a new Windows Helper build/release even if no files under `connector/` changed.
