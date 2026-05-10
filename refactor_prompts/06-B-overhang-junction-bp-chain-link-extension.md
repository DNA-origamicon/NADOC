# Refactor 06-B — Phase 4: extend `_overhang_junction_bp` for chain-link disambiguation

You are a **worker session** in a git worktree. This is a small targeted preparation refactor from the 07-FINDINGS deferred-to-next-session list. Pure additive parameter; existing callers don't change behavior.

## Pre-read (in order)

1. `CLAUDE.md` — Three-Layer Law, DNA-topology rule
2. `REFACTOR_AUDIT.md` § "Universal preconditions"
3. `refactor_prompts/07-multi-domain-overhang-audit-FINDINGS.md` — read **the entire "Phase 4 — chain-link extension to _overhang_junction_bp" section** AND the "Phase 0 — preparatory helpers" section so you understand what already shipped
4. `memory/feedback_overhang_definition.md`
5. `memory/feedback_crossover_no_reasoning.md`
6. `backend/core/lattice.py:3207-3227` — read the current helper in full
7. `backend/api/crud.py:5560-5570` — the one current caller (`patch_overhang` extrude branch)
8. This prompt

## Goal

`_overhang_junction_bp(design, helix_id) -> Optional[int]` currently returns the **first** crossover whose `half_a` or `half_b` matches `helix_id`. Today an extrude-OH helix has at most one such crossover, so "first" is unambiguous.

Phase 2 of the multi-domain rollout (chain-link extrude builder, BLOCKED on a separate user decision) will introduce extrude-OH helices with **two** such crossovers — one on the parent-side junction (root), one on the child-side junction (tip, where the next chain link anchors). Future callers (chain `patch_overhang` resize, rotation pivot derivation) will need to disambiguate.

This refactor:
1. Adds an optional `exclude_helix_id: str | None = None` parameter
2. When provided: skip any crossover whose **other half** is on `exclude_helix_id`
3. When `None` (the default): preserve current behavior exactly (return first match)
4. Is forward-compatible: zero current callers need to change

## In scope

- Modify `_overhang_junction_bp` in `backend/core/lattice.py` to accept the new optional parameter
- Update the docstring to document the new parameter and the chain-link motivation
- Add `tests/test_overhang_junction_bp.py` with cases:
  - **Single-junction default** — current production shape; one crossover on the OH helix; helper returns its bp index
  - **Single-junction with `exclude_helix_id` set to a non-matching helix** — same as default
  - **Two-junction synthetic design** — build a Design with TWO crossovers where one OH helix's `half_a` is `OH1` and `half_b` is `parent` for crossover 1; `half_a` is `OH1` and `half_b` is `child_OH2` for crossover 2. Call helper with `exclude_helix_id="parent"` → returns crossover 2's bp. Call with `exclude_helix_id="child_OH2"` → returns crossover 1's bp.
  - **None case** — helix not in any crossover → returns `None` (existing behavior)
  - **Backwards-compatibility** — call helper without `exclude_helix_id` against the two-junction Design; returns the first match (whichever crossover is first in `design.crossovers`)
- The synthetic two-junction test does NOT need a real chain-link OverhangSpec — just a Design with the right `crossovers` list. This avoids depending on Phase 2 (which is blocked).

## Out of scope

- Chain-link extrude builder (Phase 2 — blocked on user decision)
- Modifying `make_overhang_extrude` or any other lattice topology builder
- Updating `patch_overhang` to use the new parameter (that's Phase 2's caller change; we only ship the helper extension here)
- Modifying `apply_overhang_rotation_if_needed` to use the new parameter (Phase 3 work)
- Touching `_PHASE_*` constants
- Any frontend changes
- Any other helper extension

## Verification plan

### Pre-state
```bash
git status > /tmp/06B_dirty_pre.txt
just lint > /tmp/06B_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/06B_lint_pre.txt
just test > /tmp/06B_test_pre1.txt 2>&1
just test > /tmp/06B_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/06B_test_pre1.txt | sort > /tmp/06B_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/06B_test_pre2.txt | sort > /tmp/06B_baseline2.txt
comm -12 /tmp/06B_baseline1.txt /tmp/06B_baseline2.txt > /tmp/06B_stable_failures.txt

# Capture current behavior for the existing single-junction caller path:
just test-file tests/test_overhang_sequence_resize.py 2>&1 | tail -5  # exercises patch_overhang extrude branch
```

### Implementation rhythm
1. Read the current helper in full + its docstring (already includes the chain-link forward-compat note).
2. Read the one current call site (`crud.py:5564`) — confirm it doesn't need to pass the new parameter.
3. Modify the helper. Keep the body's first match as the fallback so passing `None` exactly preserves today's behavior.
4. Update docstring with the new parameter and an explicit "callers without `exclude_helix_id` get current behavior" note.
5. Run `just test` to confirm baseline preserved (no caller change → no behavior change).
6. Add `tests/test_overhang_junction_bp.py` with the 5 cases above.
7. Run `just test-file tests/test_overhang_junction_bp.py`.
8. Run full `just test` again.

### Post-state
```bash
just lint > /tmp/06B_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/06B_lint_post.txt
just test > /tmp/06B_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/06B_test_post.txt | sort > /tmp/06B_post_failures.txt
diff /tmp/06B_stable_failures.txt /tmp/06B_post_failures.txt   # MUST be empty (new tests pass; baseline preserved)

# Confirm the existing caller still works exactly the same way:
just test-file tests/test_overhang_sequence_resize.py 2>&1 | tail -5
```

## Stop conditions

- Worktree pre-state shows uncommitted edits in `lattice.py` or any of the 4 deformation/relax files (`deformation.py`, `linker_relax.py`, `crud.py`'s overhang routes): stop, report.
- Test post-failure not in stable_baseline ∪ flakes: revert, stop. The most likely cause would be an existing caller relying on the precise iteration order of `design.crossovers` — if so, that's a bigger latent bug than this refactor's scope.
- The helper's body needs a non-trivial change beyond adding one filter clause: stop, ask. The intent is "minimal preparatory extension" not a rewrite.
- Adding the new parameter requires touching `apply_overhang_rotation_if_needed` or `_anchor_for` to keep tests passing: that's Phase 3 work, not this refactor — STOP and write up.

## Output (final message)

```markdown
## 06-B `_overhang_junction_bp` chain-link extension — <REFACTORED|UNSUCCESSFUL>

### Pre-existing dirty state declaration
<git status output>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 19. `_overhang_junction_bp` chain-link disambiguation parameter — `low` ✓ REFACTORED
- **Category**: (refactor) — preparatory helper extension; backward-compatible parameter add
- **Move type**: additive (new optional parameter; existing callers unchanged)
- **Where**: `backend/core/lattice.py:3207` (helper signature + body); `tests/test_overhang_junction_bp.py` (new)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: 2 (lattice.py + new test); other-files: none
- **Transparency check**: PASS — zero current callers need updates; default-arg preserves today's behavior
- **API surface added**: 1 optional parameter on an internal helper (`exclude_helix_id: str | None = None`)
- **Visibility changes**: none
- **Callsites touched**: 0 (the one current caller `crud.py:5564` doesn't need to pass the new arg)
- **Symptom**: 07-FINDINGS Phase 4 documented that chain-link OH helices will have TWO crossovers (parent-side + child-side), and the existing helper's "first match" semantics will become ambiguous.
- **Why it matters**: lands the smallest possible API change before Phase 2 (chain-link builder) needs it. Future caller changes for chain-aware `patch_overhang` and chain rotation pivot can pass `exclude_helix_id` without further helper edits.
- **Change**: add `exclude_helix_id: str | None = None`; when provided, skip crossovers whose *other* half is on that helix.
- **Effort**: S
- **Three-Layer**: Topological — pure read accessor; no layer crossings.
- **Pre-metric → Post-metric**:
  - lattice.py LOC: <pre> → <post> (Δ small, ≤ 10)
  - tests: <pre pass> → <pre pass + N> (N test cases added)
  - lint Δ: 0
  - existing caller behavior: byte-identical (verified via `tests/test_overhang_sequence_resize.py`)
- **Raw evidence**: `/tmp/06B_*.txt`
- **Linked Findings**: 07-FINDINGS Phase 4 (this is the deferred Phase 4 implementation)
- **Queued follow-ups**:
  - Phase 2 (chain-link builder) is now unblocked from the helper-disambiguation angle; still blocked on the user's strand-traversal-vs-separate-strand DNA topology decision in 07-FINDINGS open question #1
  - Phase 3 (rotation composition) is independent and queued separately
```

## Success criteria

- [ ] `_overhang_junction_bp` signature updated with `exclude_helix_id: str | None = None`
- [ ] Helper docstring updated with the new parameter and motivation
- [ ] `tests/test_overhang_junction_bp.py` exists with 5 test cases (single-junction default, single-junction-with-non-matching-exclude, two-junction-with-each-exclude, None-case, backwards-compat-without-arg)
- [ ] Existing caller `crud.py:5564` unchanged
- [ ] No other production file modified
- [ ] `just test` passes; failure-set ⊆ stable_baseline ∪ flakes
- [ ] Lint Δ ≤ 0
- [ ] No phase constants touched, no other Phase 2/3/4/5 work attempted

## Do NOT

- Implement Phase 2 (chain-link builder) — that's blocked on user decision.
- Implement Phase 3 (rotation composition) — separate session.
- Update any current caller to pass the new parameter — they don't need it yet.
- Modify `apply_overhang_rotation_if_needed`, `_anchor_for`, `_anchor_pos_and_normal`, `_emit_bridge_nucs`.
- Add a real chain-link `OverhangSpec` in tests (use synthetic `Design` with hand-crafted `crossovers` list).
- Commit. Manager handles git operations.
- Append to `REFACTOR_AUDIT.md` from the worktree.
