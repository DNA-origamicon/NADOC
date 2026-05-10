# Refactor 11-C — Precondition #15 hardening + xpbd-orphan janitor cleanup

**Worker prompt. (b)+(framework) — small-scope hygiene pass.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — read #15 fully (the warn-only version that 10-I breached)
3. `REFACTOR_AUDIT.md` Findings #37 (10-I prune-with-caveats; precondition #15 BREACHED) + Followup 10-I (proposed framework edit #1)
4. `REFACTOR_AUDIT.md` audit-log row "2026-05-10 | dereliction" — xpbd + FEM pruned; janitor item queued for `loop_skip_highlight.js` + `domain_ends.js` orphaned `applyPhysicsPositions` methods
5. `archive/physics_xpbd_fem/README.md` (context for why these methods are now dead)

## Step 0 — CWD safety

```bash
pwd
git rev-parse --show-toplevel
```

## Goal

Two small targeted improvements, single pass:

1. **Harden precondition #15 from warn → fail.** Update the precondition body to require shell `exit 1` on CWD mismatch, not just "STOP and report". Reword Step 0 in the precondition + add a corollary about auto-cleaned-worktree edge cases.

2. **Delete orphaned `applyPhysicsPositions` methods** in:
   - `frontend/src/scene/loop_skip_highlight.js` — find the method def, verify zero callers project-wide, delete
   - `frontend/src/scene/domain_ends.js` — same

Both methods' only callers were in the `main.js` xpbd bootstrap that was deleted in the 2026-05-10 dereliction commit (`d262c20`). Verify by grep before deleting.

## In scope

### Part A — precondition #15 update

Edit the precondition body in `REFACTOR_AUDIT.md`. New phrasing should:

- Require shell `exit 1` on CWD mismatch (not "STOP and report")
- Add corollary: "if pwd does not match $EXPECTED_WORKTREE, the worker MUST exit non-zero before any code change. Manager re-dispatches with a fresh worktree."
- Cite Pass 10-I breach as the reason (and Pass 6-B as the original surfacing pass)

Suggested template:

```
15. **CWD-safety preamble (Step 0).** Every worker prompt's first executable step MUST be:

    pwd
    git rev-parse --show-toplevel
    # FAIL HARD on mismatch — do not proceed:
    if [ "$(pwd)" != "$EXPECTED_WORKTREE" ]; then
        echo "FATAL: not in worktree $EXPECTED_WORKTREE (got $(pwd))"
        exit 1
    fi

    The Agent tool's `isolation: "worktree"` sets the worktree path automatically...
    [keep existing rationale + add Pass 10-I breach citation]

    **Corollary (Pass 11-C added):** if pwd does not match $EXPECTED_WORKTREE, the worker MUST exit non-zero before any code change. Manager re-dispatches with a fresh worktree.
```

Preserve the existing rationale paragraph; just upgrade the shell check from advisory to fail-hard.

### Part B — janitor cleanup

For each of the 2 files:
1. `grep -n "applyPhysicsPositions" frontend/src/scene/<file>.js` to find the method def line range
2. `grep -rn "applyPhysicsPositions" frontend/ backend/ tests/` to find callers
3. If 0 callers (besides the def itself) → delete the method
4. Run `cd frontend && npx vite build && npx vitest run` to verify the deletion didn't break anything

## Out of scope

- Other prunes (e.g. `applyFemPositions` neutral renaming) — the worker that did the dereliction prune correctly identified those as still in use by mrdna CG-relax + oxDNA overlay paths. Leave alone.
- New preconditions beyond #15 update
- The 29 vulture@60 backlog candidates from Finding #31 — separate batched pass
- Touching ws.py / store.js / store.js / index.html (already pruned)

## Verification

3× baseline + lint pre/post per precondition #1, #2:

```bash
for i in 1 2 3; do just test > /tmp/11C_test_pre$i.txt 2>&1; done
just lint > /tmp/11C_lint_pre.txt 2>&1
cd frontend && npx vite build > /tmp/11C_vite_pre.txt 2>&1
```

Post:
- precondition #15 in REFACTOR_AUDIT.md updated (verify by reading the section)
- `applyPhysicsPositions` removed from both files
- `cd frontend && npx vite build` clean
- `cd frontend && npx vitest run` clean
- backend tests pass (no regression — these are frontend-only changes plus a doc update)
- Lint Δ ≤ 0

## Stop conditions

- Step 0 fails → STOP
- `applyPhysicsPositions` has callers in non-archived code (verify via `grep -r`) → STOP, report
- vite build fails post-deletion → revert, STOP

## Output (Findings #40)

Required:
- precondition #15 updated Y/N
- Methods deleted: file + LOC count + caller-grep verification (proof of zero live callers)
- vite build PASS/FAIL
- vitest PASS/FAIL counts
- Backend test failure set still ⊆ baseline
- Lint Δ
- Linked: #37 (10-I breach), policy row 2026-05-10 (dereliction)

## USER TODO

None needed; this is hygiene + framework. No user-visible behavior change.

## Do NOT

- Touch any non-target files
- Rename `applyFemPositions` / `clearFemOverlay` (still in use)
- Add new preconditions
- Commit / append to REFACTOR_AUDIT.md (manager aggregates)
