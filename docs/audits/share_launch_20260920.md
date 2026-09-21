# Windows sharing startup correction — 2026-09-20

The cube_pore Share link report was a launcher failure, before publishing the
package. Read-only inspection found the native host already healthy with no
published shares. A disposable Windows Node child reproduced the same PowerShell
progress CLIXML and `SIGTERM` timeout after 16.1 seconds, despite starting the child.

The launcher now uses PowerShell only to discover executable paths. A short-lived
native Node bootstrap starts the hidden, detached helper with file-backed output;
argument arrays preserve spaces and quotes. The real launcher, pointed at a
temporary bounded dummy helper, returned in 1.4 seconds while that helper remained
alive. This probe used no listener or Funnel configuration. Its files were removed
in `finally`. The existing public meeting host was not restarted.

The editor also recovers a bootstrap error only if its authenticated management
request succeeds. A stale `ready` status file alone is insufficient. Windows
bootstrap failures produce a concise message rather than an encoded shell command.

Validation:

- Native Windows/WSL bootstrap and full launcher probes passed.
- Node sharing/room/provider/launcher regressions: 11 passed.
- Frontend unit suite: 480 files, 6,703 tests passed.
- General browser smoke suite: 23 passed, including console-error and teardown gates.
- Isolated actual Help menu → copy → guest view: passed for two independent designs,
  including revocation, without browser errors. This did not test cube_pore's
  scientific display fidelity or a new public Funnel connection.
- Lint and whitespace checks passed. `main.js` LOC delta: 0.
- Backend selection: FAST; 8,789 passed, 7 skipped, 7 failed because the pre-existing
  external photoproduct review evidence archive is unavailable. Pytest took 158.52s
  while sharing CPU with the frontend suite. Two timing flags (5.26s source scan,
  5.15s coating validation) were triaged locally under the triage-slow-tests skill:
  the guarded focused rerun passed in 0.55s and 4.16s respectively. No test registry,
  budget, or scientific implementation was changed.

The backend selector's deferral was:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

Browser cleanup inventory: isolated ports 8001/5174; `__e2e__` workspace designs
and project histories owned by global teardown; session cache disabled; isolated
share credentials owned by `afterAll`, bridge credentials by global teardown.
No tests write the user's live editor state. Disposable bootstrap directories and
logs are owned by `finally`. Verification logs remain outside the workspace under
`/tmp/nadoc-launch-*.log` for this investigation.

Post-run cleanup verified: workspace 147 entries, `.projects` 0, `.session` 11,
and `playwright_tests` 57, with no additions or removals versus preflight. Isolated
share credentials and disposable native-launch directories are absent.
