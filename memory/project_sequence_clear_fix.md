---
name: Sequence clear fix — incomplete, resume next session
description: In-progress fix for "Clear sequence" right-click and "Assign Staple Sequences" not fully resetting sequence data
type: project
originSessionId: 4bd4801a-92ac-49ed-a780-4670e5b1abf0
---
## Status: SUPERSEDED — the "Assign Staple Sequences clears overhangs" part was REVERSED (2026-07-01)

**2026-07-01 reversal:** The user asked that overhang sequences be **preserved** (not
cleared or reassigned) when "Assign Staple Sequences" runs — the opposite of item 2
below. The overhang-clearing wrapper in `assign_staple_sequences_endpoint` (which by
then lived in `backend/api/routes_assign_sequences.py`, not `crud.py`) was removed.
`assign_staple_sequences` in `backend/core/sequences.py` already reads each overhang's
stored sequence via `_assemble_overhang_5to3` and threads it into the containing staple,
so preservation is automatic once the wrapper stops wiping `OverhangSpec.sequence`.
Pin: `tests/test_assign_staple_preserves_overhang_seq.py`. The "Clear sequence"
right-click (item 1) is untouched by this reversal.

**Why (original):** Sequences can accumulate errors. User wanted a clean reset path.

**How to apply:** Original clear-to-Ns intent is stale for the Assign-Staple path — do
NOT re-add overhang clearing there.

## What was done

`backend/api/crud.py` was partially edited:

1. `patch_strand` (line ~3479): when `sequence: null` is passed, now also clears all overhang sequences for that strand. This part is **DONE**.

2. `assign_staple_sequences_endpoint` (line ~3877): clears all overhang sequences before running assignment. This part is **DONE** but may need to be revised — see below.

## What the user clarified (interrupted mid-task)

The user interrupted and said:
> "Not just overhangs, the full strand sequence should be converted to Ns."

This means: "Clear sequence" and "Assign Staple Sequences" should produce a strand whose entire sequence is N×length — not null, but explicitly all-N characters. The purpose is to help clear errored sequences and reset to a known clean state.

## What still needs to be done

1. **Clear sequence right-click** (`PATCH /design/strand/{id}` with `{sequence: null}`):
   - Current behavior after partial fix: sets `strand.sequence = None` and clears overhang sequences
   - Desired behavior: set `strand.sequence` to `"N" * strand_length` (all Ns), AND clear overhang sequences
   - Alternatively: keep as null but confirm the UI renders it identically to all-N

2. **Assign Staple Sequences** (`POST /design/assign-staple-sequences`):
   - Current behavior after partial fix: clears overhang sequences before assigning (overhangs get N from scaffold complement)
   - Desired behavior: full strand sequences should also be reset to Ns first (ensure no partial old sequence bleeds through)
   - Confirm: does `assign_staple_sequences()` already replace strand.sequence entirely? It does — so the overhang clearing should be sufficient.

3. **Clarify "convert to Ns" intent**: Does the user want `strand.sequence = "N" * length` (explicit N string) or `strand.sequence = None` (null, displayed as N×length in UI)? These are semantically different — null means "unsequenced", while explicit Ns means "assigned but unknown". Ask the user to confirm before implementing.

## Key files
- `backend/api/crud.py:3451` — `patch_strand` endpoint
- `backend/api/crud.py:3860` — `assign_staple_sequences_endpoint`
- `backend/core/sequences.py:316` — `assign_staple_sequences()` logic
- `frontend/src/ui/spreadsheet.js:529` — "Clear sequence" context menu for sequence column
