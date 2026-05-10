# Followup 09-A — Evaluate `slice_plane.js` lattice-math leaf extraction

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/09-A-slice-plane-lattice-math-extract.md`
2. Worker's Findings #26 text

## Q1 — Leaf-pattern correctness (load-bearing)
`grep -nE "from\s+['\"](\.|\.\.)/" <worktree>/frontend/src/scene/slice_plane/lattice_math.js` — should return only `from 'three'`. Any relative import back to slice_plane or sibling = leaf premise broken; flag.

## Q2 — Verbatim move
For each of the 5 functions, diff body against HEAD's slice_plane.js. Byte-identical or fail.

## Q3 — slice_plane.js still works
- `cd <worktree> && just test 2>&1 | tail -3` — failure set ⊆ stable_baseline ∪ flakes.
- Confirm `slice_plane.js` LOC dropped by ≥ 25.
- Search for the named imports being used: `grep -nE "honeycombCellWorldPos|squareCellWorldPos" <worktree>/frontend/src/scene/slice_plane.js | head` — should show usage at original sites.

## Q4 — Scope
- `git -C <worktree> diff HEAD --stat` shows only `slice_plane.js` + new `slice_plane/lattice_math.js`.
- No other `frontend/src` file in diff.

## Q5 — Caller-set unchanged
The 5 helpers were module-private → no external callers existed. Confirm by grep for the function names across `frontend/src` excluding the two API files. Should return 0 (or only references inside `slice_plane.js` itself, which now use the import).

## Output (return as agent result text)

```markdown
### Followup 09-A — slice_plane.js lattice-math extract  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>
**Worktree audit context**: <path>

**Leaf-pattern correctness**: PASS/FAIL — <details>
**Verbatim-move audit**: 5/5 byte-identical | <list>
**slice_plane.js LOC**: pre <P>, post <Q>, Δ <Δ>
**lattice_math.js LOC**: <K>
**Scope**: <2 files | extras>
**Caller-set unchanged**: yes/no

**Prompt evaluation**
- Was the leaf-pattern premise sound for these 5 helpers?
- Did extraction force any visibility widening?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Implement code. Append to REFACTOR_AUDIT.md.
