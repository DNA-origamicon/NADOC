# NADOC — Project Instructions

Personal research-grade DNA-origami CAD. Python 3.12 + FastAPI, Three.js + Vite,
vanilla ES modules, `uv` for Python dependencies.

## Binding scientific rules

### Three-Layer Law

1. **Topological** — strand graph and crossover graph. Ground truth; edits happen here.
2. **Geometric** — helix axes and nucleotide positions derived from topology and B-DNA constants. Read-only output.
3. **Physical** — XPBD/oxDNA relaxed positions. Display state only; never written back to topology.

Never let physical or geometric layers mutate topology. If a fix appears to require that, stop and check assumptions.

Any uncertainty about strand polarity, helix orientation, domain traversal, or scaffold path → ask the user and implement nothing. Read [DNA topology](memory/REFERENCE_DNA_TOPOLOGY.md).

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
just test-smart           # default backend loop; fast suite, scoped
just test-affected FILE…  # tight backend loop
just test-file FILE       # one fast test file
just test-frontend        # Vitest
just fmt
just lint
just lint-memory
```

The app is at `http://localhost:5173` when both servers run. See [START.md](START.md) for setup and networking.

## Verification law

- Backend behavior change → run `just test-smart`; report its `FAST`/`fast+slow[area]` decision, pass count, and any `DEFERRED` groups verbatim.
- Frontend behavior change → run `just test-frontend` and exercise the feature in the running app. If that is impossible, lead the final report with `NOT VERIFIED IN APP` and explain why.
- Geometry/topology change → also load a representative `.nadoc` design and inspect it visually.
- Never claim a test or app check passed unless it was actually run.
- Heavy tests (`just test`, `just test-slow`, real simulations/solves/benchmarks) run only in a user-opened `just test-session`. Never bypass `scripts/test_guard.sh`, create its session marker, or set force/budget escape hatches.
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
- Before adding a feature, read [FEATURE_DEVELOPMENT.md](FEATURE_DEVELOPMENT.md). Cohesive behavior belongs in a tested module; composition roots such as `main.js` receive only imports, initialization, and thin wiring.

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

The user has a PhD in biophysics specializing in DNA origami: use dense, precise domain language. Explain programming and infrastructure simply, with concrete examples and acronyms expanded on first use. Be terse. Ask rather than guess when scientific topology or directionality is uncertain.
