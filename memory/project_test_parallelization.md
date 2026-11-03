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

Full `just test`, `test-all`, broad `test-slow`, and accumulated `test-smart` debt
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
