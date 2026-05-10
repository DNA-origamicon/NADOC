# Refactor 13-C — `cadnano-editor/main.js` comprehensive audit

**Worker prompt. (audit) — read-only investigation, same shape as 08-A (frontend comprehensive audit) but scoped to one file.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions"
3. `REFACTOR_AUDIT.md` Finding #23 (Pass 8-A frontend audit; cadnano-editor/main.js was flagged but never deep-audited)
4. `frontend/src/cadnano-editor/main.js` (2184 LOC) — read FULLY
5. `frontend/src/cadnano-editor/pathview.js` (4067 LOC) — sibling file, partially refactored in Pass 10-I
6. `.claude/rules/cadnano-2d.md` if exists — path-scoped rule for this area

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

Comprehensive audit of `cadnano-editor/main.js` to identify refactor candidates. **No code changes.** Outcome is INVESTIGATED + Findings entry.

## Audit deliverables (Findings #46)

For the file, report:

1. **Top-level structure**: imports, public exports, IIFE/module-init pattern, store integration points.
2. **God-file analysis**: is this a true god-file or a thin entry point that delegates?
3. **Closure-capture surface** (if god-file): module-mutable state, scratch objects, capture-graph between methods.
4. **Three-Layer Law check**: any violations? (topological mutations from rendering paths?)
5. **Leaf-extraction candidates**: identify 2-5 self-contained sub-clusters that could extract as leaves (palette/constants, pure-math helpers, formatting functions, etc.).
6. **Coupling to sibling files**: which other files in cadnano-editor/ does main.js call into? Are there cycles?
7. **Test coverage**: any frontend tests exercise this file? (`cd frontend && npx vitest run --coverage 2>&1 | grep cadnano-editor` if cov tooling available)
8. **Dead code candidates**: per precondition #6, flag any functions/blocks with no callers project-wide. `grep -r` the function name across `frontend/`.
9. **Apparent-bug flags**: any obvious bugs or behavioral oddities surfaced during the read.
10. **Recommended next pass(es)**: 1-3 concrete refactor proposals for Pass 14+, with prompt-template selection (09-A/10-H leaf? 10-F sub-router? 12-B closure-capture decomp?).

## Out of scope

- Modifying cadnano-editor/main.js or any other file
- Running the full backend test suite (this is a read-only audit; cd frontend test runs are OK)
- Refactoring pathview.js (separate scope; partial work done in 10-I)
- Touching any locked area

## Verification

```bash
pwd
git status --short  # should show no modifications post-audit
```

## Stop conditions

- Step 0 fails → STOP
- Any code change attempted → revert, STOP (this is read-only)

## Output (Findings #46)

Use the audit template from Finding #23 (Pass 8-A). Include:
- File LOC + import count + export count
- Coupling matrix (which sibling files imported/called)
- 2-5 leaf-extraction candidates with LOC estimates
- Recommended Pass 14+ approaches
- Linked: #23 (parent frontend audit)

## Do NOT

- Modify any file
- Commit / append to REFACTOR_AUDIT.md
- Run backend tests unless necessary
