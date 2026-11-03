# S04 isolated deformation-history execution — October 17, 2026

**Blocked at browser launch; no lifecycle acceptance.** One invocation of the
existing two-case spec returned **2 failed**, each in 2 ms, before test bodies.
S07 browser-path repair is the sole successor, unstarted; its bounded contract is
in the [handoff](session_handoff.md#next-bounded-task).

## Reconciliation and prerequisites

HEAD remains `96ab701e`; recent history matches the handoff. No applicable AGENTS.md
was found in repository/ancestor locations. Read CLAUDE.md, current handoff,
project memory, ledger, relevant acceptance/source and artifact policy. Existing
S02/S03/S05, native, CPD-exclusion and memory changes were preserved. This task
changes documentation only. Older Archive/unstarted claims are historical;
portable scratch policy applies here. Production backend and both frontend gates
were checked on disk and remain false.

Before launch, ports 8004/5177 had no listeners. Installed Chromium executable
lookup outside isolation resolved to an existing user-cache executable. This
check did not prove the child environment's browser resolution; the run exposed
that gap. The exact guarded storage command passed on `/tmp`, 661 GiB free:

```sh
just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py --check-storage
just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py
```

Only the second command launched services; it exited 1. One worker, zero retries,
only `deformation_history.spec.js`; no second invocation, repair or download.
Uvicorn reported startup complete on 8004; the Vite readiness prerequisite passed
and Playwright scheduled both cases. Both failed at `browserType.launch`:

```text
Executable doesn't exist at /tmp/__e2e__history-8avgccos/cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell
```

Read-only follow-up confirmed the corresponding executable exists at
`/home/joshua/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell`.
Installed Playwright registry source (`frontend/node_modules/playwright-core/lib/server/registry/index.js`,
lines 472–480) uses `PLAYWRIGHT_BROWSERS_PATH`, otherwise Linux `XDG_CACHE_HOME`
or the home cache. The launcher sets XDG to the empty run cache. Thus the failure
is installation-path resolution under isolation, not evidence that Chromium must
be downloaded. The initial ordinary-environment executable check was insufficient.
NO_COLOR/FORCE_COLOR warnings also appeared; no lifecycle assertion failed.

## Assertions reached and cleanup

Neither test body ran: no fixture seed/save, Open, private-render check, parameter
edit, canonical/file equality, Cancel, redo preservation, Apply, revision/history
increment, identity comparison or console-error assertion. The source contains
these checks; intended coverage is not executed coverage. No app qualification,
representative latency/memory, creation, all-gesture, broad-suite or scientific
validation is claimed. ISSUE-100/MV-48/FH-20/FH-27 stay open.

Before invoking Playwright, reviewed the matrix inventory and actual launcher,
config, app and spec. Fresh root `R=/tmp/__e2e__history-8avgccos` owns:

- `workspace/**`: two `__e2e__history-*` fixture names, project stores, metadata,
  playback and any logs. Production startup/session caching disabled.
- `tmp/**`: browser profiles/downloads/temporaries; TMPDIR/TEMP/TMP propagated.
- `cache/**`, `vite-cache/**`: UV/XDG/Playwright transforms and Vite runtime caches.
- `playwright/**`: results/last-run and failure context; screenshots/video/traces off.
- `.owner-start`: process ownership timestamp. No share/viewer credential writer.

The outer finally stops Playwright and marked descendants before deleting R,
including startup/assertion failures. Normal validation guard/cache bookkeeping
remains outside R under existing policy. No browser install was requested.
Launcher printed `Cleanup verified absent: /tmp/__e2e__history-8avgccos`.
Independent post-run checks confirmed R absent, no accessible process bearing its
exact environment marker, no listeners on 8004/5177, and no
`workspace/**/__e2e__history-*` artifacts. Process enumeration encountered 32
protected processes whose environments cannot be inspected; no claim to inspect
or terminate them is made. The launcher's owner/time filtering and successful
cleanup, together with free ports, provide the owned-process cleanup evidence.
No leftover owned payload remains. Deleted bytes were not metered by the existing
launcher; do not invent a size. Retained only this compact report and record edits,
not raw captures/logs. Installed browser/runtime and user designs remain intact.

## Closeout

No source repair or successor work. Fixed milestone exits and scientific/test
rules unchanged; no rollout, commit or push. **21/38 complete; 17 remaining
(8 core, 9 parked); delta +0 completed / +0 total; U1–U54 unchanged.** Historical
full backend run remains failed; no broad rerun or baseline clearance.
Documentation validation: `just lint-memory` passed (0 errors, 0 warnings);
`git diff --check` passed. Scoped link check resolved 18 local file targets in
the handoff/report and newly added evidence links (not a repository-wide anchor
audit). Ledger check confirmed 38 unique IDs, 21 Done; handoff has exactly one
next-task ID, S07. Reviewed current records and scoped diff/status; existing
source/test changes remain outside this documentation-only task.
