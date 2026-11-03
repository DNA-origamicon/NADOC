# Validation rules — unified Watson-Crick polarity test (2026-05-02) — supporting detail

[Topic head](../../project_overhang_connections.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Validation rules — unified Watson-Crick polarity test (2026-05-02)

One test for all 16 (end_a, attach_a, end_b, attach_b) combos. Define each
side's polarity:

```
comp_first := (5p AND free_end) OR (3p AND root)
```

`comp_first` means the linker strand traverses `[complement, bridge]` (the
bridge attaches at the complement's 3' end). `bridge-first` is the inverse.

- **dsDNA accepted iff `comp_first(A) == comp_first(B)`** — both bridge halves on the virtual `__lnk__` helix run antiparallel and form a real Watson-Crick duplex. Mismatched polarity makes them parallel — non-physical.
- **ssDNA accepted iff `comp_first(A) != comp_first(B)`** — single strand traverses `[complement_a, bridge, complement_b]` (5'→3'), so the boundary at A is at complement_a 3' (comp-first) and at B is at complement_b 5' (bridge-first). Both sides agreeing breaks the continuity.

Eight of 16 combos accepted for each linker type; the two sets are disjoint. Implementation: [`_check_linker_compatibility` + `_comp_first_polarity` in backend/api/crud.py](../../../backend/api/crud.py) and frontend mirror [`_checkRules` + `_compFirst` in overhangs_manager_popup.js](../../../frontend/src/ui/overhangs_manager_popup.js).

**Examples** — both `5p+free_end / 5p+free_end` and `5p+free_end / 3p+root` are valid ds (matching polarity); `5p+free_end / 5p+root` is invalid ds (would force a parallel duplex). The same combos give the inverse for ss (the first two are invalid ss; the third is valid).

**Per-end uniqueness** (`_used_overhang_ends`): each `(overhang_id, attach)` pair can appear in at most one connection. Backend returns 400 with "already linked at its {root|free end}".

**Per-end uniqueness** (`_used_overhang_ends`): each `(overhang_id, attach)` pair can appear in at most one connection. Backend returns 400 with "already linked at its {root|free end}".
