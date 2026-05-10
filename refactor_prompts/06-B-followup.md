# Followup 06-B — Evaluate `_overhang_junction_bp` chain-link extension

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/06-B-overhang-junction-bp-chain-link-extension.md`
2. `refactor_prompts/07-multi-domain-overhang-audit-FINDINGS.md` Phase 4 section
3. Worker's Findings #19 text

## Q1 — Helper signature + behavior

- `grep -n "def _overhang_junction_bp" <worktree>/backend/core/lattice.py` — confirm new signature is exactly `_overhang_junction_bp(design: Design, helix_id: str, exclude_helix_id: str | None = None) -> Optional[int]` (or equivalent type-hint style consistent with the file).
- Read the body. Confirm: when `exclude_helix_id is None`, the body is functionally identical to before (returns first-match crossover). When `exclude_helix_id is not None`, crossovers whose OTHER half is on `exclude_helix_id` are skipped.
- The default-arg behavior MUST preserve byte-equivalent semantics to the prior helper. Verify by mental walk-through.

## Q2 — Test coverage

Run `just test-file tests/test_overhang_junction_bp.py` in the worktree. All declared tests should pass.

Open the test file. Confirm 5 cases exist:
1. Single-junction default (current production shape)
2. Single-junction with non-matching `exclude_helix_id`
3. Two-junction synthetic Design with `exclude_helix_id="parent"` → returns child-side bp
4. Two-junction synthetic Design with `exclude_helix_id="child_OH2"` → returns parent-side bp
5. None case (helix not in any crossover) → returns `None`
6. (Bonus) Backwards-compat: two-junction with no `exclude_helix_id` → returns first match per iteration order

If fewer than 5 substantive cases, flag.

## Q3 — Existing caller untouched

- `grep -n "_overhang_junction_bp" <worktree>/backend/api/crud.py` — confirm the call still uses the 2-argument form (`_overhang_junction_bp(design, spec.helix_id)`), no `exclude_helix_id` keyword.
- `git -C <worktree> diff HEAD -- backend/api/crud.py` — should be empty.

## Q4 — Existing test invariants preserved

`just test-file <worktree>/tests/test_overhang_sequence_resize.py` — must pass with the same assertions, since the existing caller wasn't changed and the default-arg path is unchanged.

## Q5 — Scope

- `git -C <worktree> diff HEAD --stat`: only `backend/core/lattice.py` + new `tests/test_overhang_junction_bp.py`.
- No edits to `deformation.py`, `linker_relax.py`, `_anchor_for`, `_emit_bridge_nucs`, or any frontend file.
- No edits to `_PHASE_*` constants.

## Q6 — Phase 2 readiness

The whole point of this refactor is to unblock Phase 2 (chain-link builder) from the helper-disambiguation angle. Read the helper's new docstring: does it explain the parameter clearly enough that a future Phase 2 worker would know to pass `exclude_helix_id=parent_overhang.helix_id` when looking for the child-side junction? If the docstring is unclear, flag for improvement.

## Output

```markdown
### Followup 06-B — `_overhang_junction_bp` chain-link extension  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>
**Worktree audit context**: <path>
**Diff vs claimed-touched files**: <2 claimed | M observed>

**Helper signature audit**
- New parameter present: yes/no
- Default-arg behavior preserved: yes/no
- Body's `exclude_helix_id` filter: <correct | flag — describe>

**Test coverage audit**
- Declared test cases: <N> (≥ 5 expected)
- All pass: yes/no

**Existing-caller-untouched audit**
- `crud.py:5564` call: <unchanged | flag>
- `test_overhang_sequence_resize.py` still passes: yes/no

**Scope audit**
- files-changed: <2 | extras>
- locked / sensitive areas untouched: <yes/no>

**Phase-2-readiness audit**
- Docstring clarity for chain-aware caller: <good | flag>

**Prompt evaluation**
- Was the synthetic-Design test approach sufficient, or did it need a real chain OH?
- Any unanticipated behavior in the helper's iteration order?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Implement Phase 2, Phase 3, or Phase 5 work.
- Add new test cases yourself.
- Append to REFACTOR_AUDIT.md.
