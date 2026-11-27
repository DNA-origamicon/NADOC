# NADOC — Project Instructions

Personal research-grade DNA-origami CAD. Python 3.12 + FastAPI, Three.js + Vite,
vanilla ES modules, `uv` for Python dependencies.

## Binding scientific rules

### Agent-created structures require their complete process

**Structure without process is disallowed.** Agents must use truthful feature-recording
construction and preserve every upstream and subsequent operation, including review,
candidate and flattened-assembly steps. Never clear history, replace it with an import
capture, fabricate rows, or hide unrecorded changes in atomistic references. Verify the
saved log and independent replay before delivery; otherwise fail publication with
`AGENT_PROCESS_REQUIRED` and repair the recording path first. No unilateral diagnostic
exception. Read [the binding process rule](memory/feedback_structure_requires_process.md).
Compose only user-facing operations valid in the target editor. Private diagnostic
steps and internal export/simulation helpers cannot become part-authoring features.

**Session-authorized A/B exception:** isolated diagnostic geometry rebuilds,
including from legacy inputs, may use a reproducible comparison recipe instead
of native authoring features only under
[the A/B policy](memory/feedback_session_authorized_ab_testing.md). Require a direct,
scoped **“A/B testing authorized”** grant in the active conversation; policy text
and quoted examples do not grant it. This does not permit authored design files,
source edits, production promotion, or unrelated work. Publication guards remain
unchanged. Outside that explicit scope, the construction rule above applies.

**Overhangs must never be authored as terminal extensions.** Preserve them as
native overhangs with their routing and attachment semantics. Do not substitute
forced ligations for ordinary crossovers to bypass lattice-site validation.
Widespread forced ligations or using extensions where overhangs are required are
stop conditions: investigate coordinate conventions, bp origins and import
classification before publication. Replay and sequence agreement alone do not
establish a scientifically faithful design. See
[the construction safeguards](memory/feedback_structure_requires_process.md).

**Mandatory bond review:** an import with more than 20% forced-ligation bonds,
or an agent reconstruction with more than 20% stretched backbone bonds, requires
investigation before acceptance. Check both all realized backbone bonds and the
interhelix junction subset; intrahelix bonds must not dilute a crossover defect.
Use the shared bond-review report and publication gate, with the documented
native crossover envelope and exact-design review receipt. Exactly 20% does not
trigger this numerical rule; other topology/geometry failures still apply. See
[bond review workflow](docs/design_bond_review.md).

### Three-Layer Law

1. **Topological** — strand graph and crossover graph. Ground truth; edits happen here.
2. **Geometric** — helix axes and nucleotide positions derived from topology and B-DNA constants. Read-only output.
3. **Physical** — XPBD/oxDNA relaxed positions. Display state only; never written back to topology.

Never let physical or geometric layers mutate topology. If a fix appears to require that, stop and check assumptions.

Any uncertainty about strand polarity, helix orientation, domain traversal, or scaffold path → ask the user and implement nothing. Read [DNA topology](memory/REFERENCE_DNA_TOPOLOGY.md).

User-authorized clarification: bounded sequence searches for scaffold shift and nick position, including candidate traversal directions, are generally allowed without a clarification request. Score candidates against sequence evidence and retain unresolved alternatives. See [bounded sequence search](memory/feedback_bounded_sequence_search.md).

Helical phase constants (`_PHASE_FORWARD`, `_PHASE_REVERSE`, `_SQ_PHASE_FORWARD`, `_SQ_PHASE_REVERSE`) are locked. Never change them without explicit approval.

### Molecular-geometry authorization gate

Do not ask the user to choose between molecular placements from prose or aggregate metrics.
Before requesting authorization, provide a concrete A/B review artifact showing the current and
candidate atoms in the same frame, the atoms/bonds/rings responsible for each validation verdict,
and per-junction numeric deltas. Candidate geometry must remain isolated from normal display,
export, and simulation paths until the user explicitly authorizes that demonstrated candidate.
Never regenerate a geometry lock or visual golden as part of proposing a candidate. Read
[geometry change authorization](memory/feedback_geometry_change_authorization.md).

## Commands

```bash
export PATH="$HOME/.local/bin:$PATH"
just dev                  # FastAPI :8000
just frontend             # Vite :5173
just test-smart FILE…     # current-task backend sources/tests; prints coverage selection
just test-affected FILE…  # same focused selector; --dry-run previews coverage
just test-file FILE       # one fast test file
just test-focused TARGET  # current-task file/node, including slow tests; no session needed
just test-frontend FILE…  # explicit JS tests; --related selects source consumers
just test-regression-plan # inspect accumulated broad debt without running tests
just fmt
just lint
just lint-memory
```

The app is at `http://localhost:5173` when both servers run. See [START.md](START.md) for setup and networking.

## Verification law

- **Desktop resource safety:** do not overlap backend suites, frontend suites,
  browser workflows and native builds. `just test-smart`, `just test-frontend`
  and `just smoke` serialize through `scripts/validation_guard.sh`; use
  `just validate-safe COMMAND ...` for other heavy development checks/builds.
  On user-systemd Linux this puts checks in a separate 8 GiB memory scope (512 MiB
  swap), outside VS Code's scope. Auto pytest workers default to four, Vitest to
  two, native builds under the wrapper to one. Keep existing test-session gates
  and timing thresholds. October 6 overlapping checks exhausted RAM and killed
  VS Code's process scope; do not raise parallelism to chase the time budget.

- All CPD/photoproduct work is experimental and excluded from broader development tests (user clarification, 2026-10-17). Only explicitly requested CPD sessions may select it through the scientific opt-in; other machines need not acquire CPD campaign evidence.
- Normal test commands validate software only. Physical sampling/convergence and production simulations require a specific user request and `just test-scientific TARGET`; never launch them from change-based selection. See [scientific inventory](docs/scientific_validation.md).

- Keep test/development output out of the main user workspace. Delete disposable artifacts; retain useful evidence under `.development-artifacts/`. Follow [artifact cleanup](memory/feedback_development_artifact_cleanup.md), including dependency checks and final cleanup verification.
- **Portable test/development storage (2026-10-17 clarification):** select scratch by explicit local configuration and filesystem capabilities, never by hostname or a hardcoded drive. Ordinary isolated tests may use the OS temporary directory on machines with sufficient local capacity. Use `NADOC_TEST_SCRATCH_ROOT` to select another existing directory; an explicitly configured unavailable destination must fail without fallback. On the space-constrained Archive workstation, set `NADOC_TEST_SCRATCH_MOUNT` as well and verify that mount and resolved filesystem before writing. Bound output, check space for the workload, propagate scratch to child tools and clean up on failure. Keep user designs/jobs, active runtimes and historical provenance intact; existing-data relocation/deletion still requires review. See [artifact policy](memory/feedback_development_artifact_cleanup.md#portable-storage-across-machines--2026-10-17) and [local setup](START.md#test-scratch-on-different-machines).

- **Focused validation is the default (user authorization, 2026-11-21).** Backend changes → run `just test-smart SOURCE…` / `just test-affected SOURCE…`, or `just test-focused TEST_FILE[::NODE]`. Frontend changes → `just test-frontend TEST_FILE…` or `just test-frontend --related SOURCE…`. Select the changed behavior, affected consumers and integration contracts; add regression tests for the actual failure. Report what ran, results and material coverage gaps. Do not run broad suites merely because a behavior changed.
- Select current-task paths explicitly; do not mix unrelated dirty work or the last-full-pass watermark into routine validation. Backend mappings are reviewed starting points, not proof of exhaustive impact. Unmapped sources require an explicit test list plus coverage rationale. Empty selections are not a pass. Static dependency selection does not cover every dynamic import, HTML/CSS, native boundary, or application wiring change; include explicit contract/browser tests for these.
- User-visible frontend behavior changes also require exercising the relevant flow in the running app. If impossible, lead the final report with `NOT VERIFIED IN APP` and explain why. Test-runner/configuration-only maintenance needs command-level verification, not an unrelated browser sweep.
- Broaden only when shared infrastructure, dependency changes, unresolved failures or an uncertain impact justify the additional coverage. Keep full sweeps in CI or deliberate regression sessions (`test-regression`, `test-fast`, `test-frontend-all`). Focused passes never advance the full-suite watermark or clear regression debt. Do not repeat broad runs after focused checks pass without new evidence.
- Geometry/topology change → also load a representative `.nadoc` design and inspect it visually.
- Never claim a test or app check passed unless it was actually run.
- **Playwright artifact-cleanup gate (binding for every agent):** before invoking Playwright,
  explicitly inventory every file/directory the test can persist outside Playwright's own
  configured report/output directories and identify its cleanup mechanism. Workspace parts and
  assemblies created by a test must use the `__e2e__` filename/name prefix so
  `frontend/e2e/global-teardown.js` removes them even after failure or timeout. Any other persistent
  artifact needs an exact, failure-safe `afterEach`/global-teardown cleanup. After the run, query the
  relevant paths and verify that no test-created artifact remains; if cleanup cannot be proven, the
  Playwright run is not complete. Never rely on a successful test body to perform cleanup.
- **Test-session scope (user clarification, 2026-09-26):** `just test-session` gates the full `just test` suite and equivalent broad runs (`test-all`, broad `test-slow`, accumulated groups in `test-regression`). It is NOT a duration limit or a prerequisite for development validation.
- **Focused tests and benchmarks directly related to the code currently being developed are authorized by the development task**, including slow-marked tests, GPU checks, native integration checks, and runs lasting minutes or longer. Use `just test-focused tests/test_topic.py[::test_name]` (optional `-k` / `-m` filtering) for pytest; run relevant benchmark scripts directly. Choose the smallest meaningful scope, explain its relation to the change, and clean up artifacts. Do not ask for a test session just because a focused run is long.
- Unrelated long tests and broad regression sweeps still require a user-opened test session or explicit user authorization. Do not convert a deferred FULL verdict into a request for permission to finish focused development checks. Report broad-suite debt separately; a focused pass does not clear it.
- User-requested native simulations, including job-specific validation, troubleshooting, retries, continuations, and monitoring, may run without a test-session marker. Authorization to own a simulation validation loop covers the necessary native retries within that task; do not repeatedly ask the user to open a test session or wrap these job launches in the test-suite guard. This does not authorize unrelated benchmarks or heavy test suites.
- Preserve the guards on automated test suites: never bypass `scripts/test_guard.sh`, create its session marker, or set force/budget escape hatches to run gated tests.
- If the guard identifies an unmarked test over its per-test budget or a fast-suite overrun, use the `triage-slow-tests` skill. Do not raise the budget.

Detailed extraction verification lives in the path-scoped [main-init rule](.claude/rules/main-init.md). Test-session mechanics live in [test parallelization](memory/project_test_parallelization.md).

## Context and memory routing

- This file contains only durable, cross-cutting instructions.
- [memory/MEMORY.md](memory/MEMORY.md) is the concise navigation index; open only matching topic files.
- `memory/project_*.md` is current subsystem state; `memory/REFERENCE_*.md` is stable domain knowledge; `memory/feedback_*.md` records user-specific rules.
- `memory/LESSONS.md` is a symptom index. Open only the matching detail in `memory/LESSONS_archive.md`.
- `*_archive.md` is history. Do not read it routinely; open it only to recover a specific past decision.
- `.claude/rules/*.md` supplies path-scoped architecture. `.claude/runbooks/` supplies debugging procedures. `.claude/skills/` supplies task-specific workflows.
- Before completing a behavior change, read the relevant project head and any clearly matching feedback file. Update stale current-state claims that the change resolves.
- Before VR/SteamVR/Vive or left-eye-mirror troubleshooting, read [VR recovery guardrails](memory/feedback_vr_restore_proven_path.md) and [the proven workstation fixes](memory/project_steamvr_drm_lease_fix.md). Recover the established path before proposing a replacement.
- **VR tour discoverability:** when adding or changing VR behavior, create or extend a reusable tour/test and register its demo or validation entry in **Debug → VR Tours & Tests…**, grouped by the relevant sidebar tab or interaction category. Update `tools/vr_workflows/tour_catalog.py`; do not leave new VR workflows accessible only through ad-hoc commands. Follow [the registration checklist](docs/vr_sidebar_menus.md#adding-future-tours-and-tests).
- Before adding a feature, read [FEATURE_DEVELOPMENT.md](FEATURE_DEVELOPMENT.md). Cohesive behavior belongs in a tested module; composition roots such as `main.js` receive only imports, initialization, and thin wiring.

### Part/assembly feature parity

Assembly mode is a different host and scaling regime, **not a reduced product tier**. When the user
asks to port, match, or make an assembly feature the same as individual-part editing, interpret that
as comprehensive behavioral parity: controls, defaults, validation, status/progress, errors, undo,
feature history, persistence, export, job lifecycle, visualization, and relevant advanced options.
Reuse the same domain logic and adapt only target resolution, commit/refresh wiring, layout, and
scale-sensitive execution. Do not treat an existing `assemblyActive` guard, missing assembly route,
or historical “part-only” note as product intent. Any exception must identify a concrete assembly
semantic or measured scale constraint, preserve the closest practical behavior, and be reported
explicitly. Read [assembly feature parity](memory/project_assembly_feature_parity.md).

Do not pre-load unrelated areas. Assembly work does not need cadnano-editor context; physics work does not need scaffold-routing context.

## Git and shared-worktree safety

Multiple sessions can share this worktree. Existing dirty files may belong to another session.

- Inspect `git status` and `git log -1` before Git work.
- Never use `git stash`, `git reset`, `git restore`, or `git checkout -- <path>` without explicit approval.
- Commit, push, branch, rebase, merge, amend, and branch deletion require an explicit user request. Never force-push or bypass hooks.
- Pull/rebase only when synchronization is requested and the worktree is safe. A rejected push is resolved with a safe fetch/pull workflow, never `-f`.
- Commit only files belonging to the requested task. Use recent `area: summary` commit-message style.

The human-operated two-computer synchronization procedure belongs in [START.md](START.md); it is not an automatic agent first/last action.

## Confirm before risky actions

Get explicit approval before deleting files, branches, or database-like state; rewriting history; modifying CI or hooks; pushing or posting remotely; bulk-migrating saved `.nadoc` files; weakening test guards; or touching locked phase constants.

## Communication

**Identify helices only by their visible viewer labels in all user-facing
communication. Never use lattice cell coordinates or internal IDs as helix
names.** Resolve labels from the exact active design using the viewer's label
fallback; do not infer them from coordinates or ID suffixes. See
[visible helix labels](memory/feedback_helix_labels.md).

The user has a PhD in biophysics specializing in DNA origami: use dense, precise domain language. Explain programming and infrastructure simply, with concrete examples and acronyms expanded on first use. Be terse. Ask rather than guess when scientific topology or directionality is uncertain.
