---

name: project_test_parallelization
description: Backend test suite runs in parallel (pytest-xdist); slow-test registry + global-state isolation gotcha
metadata: 
  node_type: memory
  type: project
  originSessionId: 2557a198-2648-4182-8f9b-1f6ff948cb26
---

# Test selection and resource isolation

Current test policy (2026-09-20): normal commands validate software only. Production,
equilibrium sampling and physical convergence campaigns require explicit
`just test-scientific TARGET`; see [inventory](../docs/scientific_validation.md).
Historical full-run commands/results below predate this split; the legacy
`NADOC_RUN_OXDNA_SLOW` flag no longer enables campaigns.

## Focused defaults — November 21, 2026

The user authorized replacing mandatory broad per-change suites with focused
validation. This supersedes older “always run fast” guidance and archived timings.
`just test-smart SOURCE…` and `just test-affected SOURCE…` now use explicit current-task
paths and `scripts/test_impact.json`. Known sources select reviewed regression tests;
unmapped sources require `--test FILE` (repeatable) plus `--reason` explaining coverage.
Mappings are starting points: inspect affected consumers and add contract tests.
No paths, missing files and unresolved selections fail visibly; there is no full-suite
fallback. `--dry-run` prints selection without launching. Related slow software tests
remain included. Scientific opt-ins are unchanged.

`just test-frontend TEST_FILE…` runs explicit files; `--related SOURCE…` uses Vitest's
static dependency graph. Paths may be repo-relative or frontend-relative. Use explicit
contracts/browser tests for HTML/CSS, computed imports and app wiring. Empty related
selections retain Vitest's failing exit status. `test-frontend-watch` also requires
explicit paths and holds the validation lock until stopped. Three audited pure test files now use
Node (library filename, websocket URL, trajectory memory); DOM tests retain jsdom and
isolation. Further environment migration should follow inspection and focused checks.

`test-focused`, `test-affected`, frontend selection and `test-file` now use the shared
validation wrapper as well as their applicable pytest guards. Worker/memory limits
and numeric thread limits are unchanged. Full local sweeps are explicit session-gated
`test-regression`, `test-fast` and `test-frontend-all`; `test-regression-plan` is read-only.
CI continues broad frontend and non-slow/non-integration backend coverage. No focused
pass updates `.nadoc-test-watermark` or clears `.nadoc-slow-pending`.

The prior watermark is August 28; the November 21 dry run considered 9,102 paths.
The previous broad backend run took 564s, frontend 514s; a focused three-file frontend
run passed 32 tests in 2.83s. These are observations, not promised future budgets.
Testmon remains uninstalled: 2.3.1 is available, but the older 2.2.0 compatibility
failure needs an isolated trial before adoption. It is not required for these defaults.

## Request-to-validation sequence

For each request, identify the changed behavior and consumers before choosing tests.
Use explicit current-task paths (not all dirty files). Preview uncertain backend
selection with `just test-smart SOURCE… --dry-run`; unmapped sources need reviewed
`--test FILE` entries and `--reason`. Run the selected backend checks and either
explicit frontend tests or `just test-frontend --related SOURCE…`, serially under
the resource wrapper. Exercise the specific browser flow for user-visible changes.
After a relevant pass, stop testing unless new edits, failures or coverage gaps
justify more. Report targets/results and remaining gaps; do not append a broad
suite as a routine final gate. A focused pass does not settle broad regression debt.

For maintenance-only audits, reuse still-applicable browser evidence rather than
rerunning UI workflows when no application behavior changed. Timings describe test
execution, not total agent investigation/implementation time; do not claim that
focused validation proves a whole request will finish in seconds.

November 21 cycle verification: the welcome-menu request selected six backend
filesystem/API tests and seven related frontend files (147 tests), all passing.
Measured sequential command wall time, including launch/guard overhead: 6.05s
backend + 11.15s frontend = 17.20s, versus the prior broad suite runner times of
564s + 514s. Coverage is deliberately focused, not equivalent to the broad sweep.
No UI code changed in this verification, so the existing five browser checks
(53.5s, passed) were reused, not rerun. The memory index's stale “broad fast checks”
pointer was corrected. Exact commands/results: `.development-artifacts/focused-cycle-verification.json`.

## November 11 full regression

Full `just test` at `12958aee`: 21,492 passed, 8 failed, 26 skipped (41m50s).
Four obsolete harness/fixture expectations were corrected; the mixed-module
CPD display parameter now carries the required scientific opt-in marker.
mrDNA zero-step accuracy, corner fold clashes and rod DNA/gold clearance remain
failing software regressions. No tolerances were relaxed and no molecular
candidate was promoted. Evidence: `.development-artifacts/full-test-20261111/`.

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

All CPD/photoproduct experiments are excluded from general tests under the October 17 user clarification. Use current [scientific-selection policy](../docs/scientific_validation.md). Keep resource serialization and test-session guards; historical flags and timing results below do not override the current scope rule.

## Desktop memory isolation (2026-10-06)

A global OOM during overlapping pytest, Vitest, Playwright and C++ compilation
ended `app-com.microsoft.VSCode-8437.scope` with `oom-kill`. Kernel task accounting
also showed about 8.1 GiB in Steam web helpers; this was combined machine pressure,
not evidence of a VS Code extension leak. Do not run heavy checks concurrently.

`validation_guard.sh` serializes smart/frontend/smoke checks and creates a separate
user-systemd scope (6 GiB high, 8 GiB max, 512 MiB swap). On systems without a user
manager it explicitly reports that only serialization/worker caps apply.
`just validate-safe COMMAND ...` provides the same protection for native builds
and custom browser workflows. Existing backend test gates remain unchanged.
Auto xdist defaults to four workers; Vitest uses two. All guards preserve failure
exit statuses. Timing debt remains visible rather than increasing budgets.

November 2 regression diagnosis: full-suite recipes now use the same one-thread
BLAS/OpenMP default as focused and fast runs. The former `slow=1` exception
oversubscribed numerical work and violated native recipe runtime fingerprints
(17 explicit runtime-mismatch failures in the broad feature-history run).
Session, serialization, memory and timing guards remain unchanged.

## Current scope rule — user clarification, 2026-09-26

`just test-session` authorizes full/broad regression sweeps, not elapsed test time.
Focused tests, GPU/native integration checks, and benchmarks directly related to
current development may run for minutes or longer without a session. The task
already authorizes that validation. Use `just test-focused TARGET` for a specific
pytest file/node, optionally filtered with `-k` or `-m`; relevant benchmark scripts
may run directly. Never ask for a session solely because these checks are slow.

Full `just test`, `test-all`, broad `test-slow`, and accumulated `test-regression` debt
remain gated, as do unrelated long tests. Focused runs retain the execution lock,
nice priority, and real exit status; they neither enforce fast-suite duration
budgets nor clear full-suite debt/watermarks. Explicit file/node selection avoids
accidentally sweeping unrelated slow tests. Scientific campaigns retain their
separate user-authorization requirement.

The obsolete July wording “heavy tests no longer run at all in an ordinary coding
session” caused repeated unnecessary permission requests. This section supersedes
that wording in historical logs. `slow` means exclusion from broad fast sweeps,
not exclusion from development. Full-suite DEFERRED messages are separate from
completion of relevant focused checks.

<a id="historical-timing-and-suite-implementation-notes"></a>
- [Historical timing and suite implementation notes](details/project_test_parallelization/01-historical-timing-and-suite-implementation-notes_archive.md#historical-timing-and-suite-implementation-notes)

- [Historical timing and suite implementation notes — continued detail](details/project_test_parallelization/01-historical-timing-and-suite-implementation-notes_archive.md)

- [Historical timing and suite implementation notes — continued detail](details/project_test_parallelization/02-historical-timing-and-suite-implementation-notes_archive.md)

- [Historical timing and suite implementation notes — continued detail](details/project_test_parallelization/03-historical-timing-and-suite-implementation-notes_archive.md)
