# Refactor 13-D — `joint_renderer.js` comprehensive audit

**Worker prompt. (audit) — read-only investigation, same shape as 13-C.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions"
3. `REFACTOR_AUDIT.md` Finding #23 (Pass 8-A frontend audit; joint_renderer.js was flagged but never deep-audited)
4. `frontend/src/scene/joint_renderer.js` (1947 LOC) — read FULLY
5. `frontend/src/scene/assembly_joint_renderer.js` (1339 LOC) — sibling? potential overlap/duplication
6. `frontend/src/scene/helix_renderer.js` (3925 LOC, partially audited) — pattern reference

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

Comprehensive audit of `joint_renderer.js` to identify refactor candidates. **No code changes.** Outcome is INVESTIGATED + Findings entry.

## Audit deliverables (Findings #47)

Same 10-point structure as 13-C:

1. Top-level structure (imports, exports, init pattern)
2. God-file vs delegate analysis
3. Closure-capture surface map (if god-file)
4. Three-Layer Law check
5. Leaf-extraction candidates (2-5)
6. Coupling to sibling files — **PARTICULAR ATTENTION**: relationship to `assembly_joint_renderer.js` (1339 LOC sibling; potential duplication or shared kernel)
7. Test coverage
8. Dead code candidates (precondition #6)
9. Apparent-bug flags
10. Recommended next pass(es)

## Out of scope

- Modifying joint_renderer.js or any other file
- Refactoring assembly_joint_renderer.js (separate Pass 14+ if duplication surfaces)

## Verification

```bash
pwd
git status --short  # no modifications post-audit
```

## Stop conditions

- Step 0 fails → STOP
- Any code change attempted → revert, STOP

## Output (Findings #47)

Audit template from Finding #23. Special attention to joint_renderer vs assembly_joint_renderer — are they duplicates, complementary, or coupled?

## Do NOT

- Modify any file
- Commit / append to REFACTOR_AUDIT.md
