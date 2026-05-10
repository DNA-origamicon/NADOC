# Refactor 13-E — `assembly_renderer.js` comprehensive audit

**Worker prompt. (audit) — read-only investigation, same shape as 13-C/D.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions"
3. `REFACTOR_AUDIT.md` Finding #23 (Pass 8-A frontend audit; assembly_renderer.js was tagged but never deep-audited)
4. `frontend/src/scene/assembly_renderer.js` (1439 LOC) — read FULLY
5. Related: `frontend/src/scene/assembly_joint_renderer.js`, `frontend/src/scene/helix_renderer.js` (partially audited; pattern reference)

## Step 0 — CWD safety (precondition #15 HARDENED)

```bash
pwd
git rev-parse --show-toplevel
if [ "$(pwd)" != "$EXPECTED_WORKTREE" ]; then
    echo "FATAL: not in worktree $EXPECTED_WORKTREE (got $(pwd))"
    exit 1
fi
```

## Goal

Comprehensive audit of `assembly_renderer.js` to identify refactor candidates. **No code changes.** Outcome is INVESTIGATED + Findings entry.

## Audit deliverables (Findings #48)

Same 10-point structure as 13-C/D:

1. Top-level structure
2. God-file vs delegate analysis
3. Closure-capture surface map (if god-file)
4. Three-Layer Law check
5. Leaf-extraction candidates
6. Coupling to sibling files (helix_renderer, joint_renderer, assembly_joint_renderer)
7. Test coverage
8. Dead code candidates
9. Apparent-bug flags
10. Recommended next pass(es)

## Out of scope

- Modifying assembly_renderer.js or any other file
- Refactoring sibling renderers

## Verification

```bash
pwd
git status --short  # no modifications post-audit
```

## Stop conditions

- Step 0 fails → STOP
- Any code change attempted → revert, STOP

## Output (Findings #48)

Audit template from Finding #23. Note relationship to helix_renderer (which extracts palette in Pass 10-H; can the same template apply to assembly_renderer?).

## Do NOT

- Modify any file
- Commit / append to REFACTOR_AUDIT.md
