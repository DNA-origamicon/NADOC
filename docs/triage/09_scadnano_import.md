# Feature 09: scadnano Import
**Phase**: A (Foundation)

---

## Feature Description

Imports scadnano JSON files into NADOC `Design` objects.

**Key file**: `backend/core/scadnano.py::import_scadnano()`
**API route**: `POST /api/design/import/scadnano`
**Test file**: `tests/test_scadnano.py`

### scadnano Format
scadnano encodes strand topology differently from caDNAno:
```json
{
  "version": "0.19.0",
  "grid": "honeycomb",
  "helices": [{"grid_position": [0, 0]}, ...],
  "strands": [
    {
      "color": "#f74308",
      "domains": [
        {"helix": 0, "forward": true, "start": 0, "end": 32},
        {"helix": 1, "forward": false, "start": 0, "end": 32}
      ]
    }
  ]
}
```

A crossover is implied when two consecutive domains in a strand are on **different helices** at the same bp boundary (end of domain 0 == start of domain 1). 

**Post-overhaul requirement (user-confirmed)**: All crossovers (scaffold AND staple) must appear in `Design.crossovers` after import.

### Special cases
- **Loopout**: non-helix domain `{"loopout": N}` between two helix domains — this is an N-base single-stranded bridge, not a crossover
- **Deletion/Insertion**: `"deletions": [bp]` and `"insertions": [[bp, count]]` within domains
- **StrandExtension**: `"extension_num_bases": N` at domain termini
- **PhotoproductJunction**: CPD fork extension (`photoproduct_junctions` top-level array)

---

## Pre-Condition State

- `test_scadnano.py` exists — unknown whether tests assert `design.crossovers` is populated
- `import_scadnano()` was written before `Design.crossovers` existed — likely does not populate it
- Loopout domains are a special case: they appear between helix domains but are NOT crossovers
- `crud.py` line ~1036 is the API endpoint; post-import flow calls `autodetect_all_overhangs()` and `_init_multiscaffold_clusters()`

---

## Clarifying Questions

1. For **loopout domains** (an N-base single-stranded bridge between two helices, not a DX crossover): how should these appear in 3D?
   - (a) Rendered as a curved tube/arc by `crossover_connections.js` (needs a loopout flag on the Crossover model)
   - (b) Rendered as a separate overhang-style element, not in `design.crossovers`
   - (c) Ignored visually for now (Phase A scope: just ensure they don't crash anything)

2. scadnano's `"none"` grid type means a free-form design with no lattice. NADOC only supports HC and SQ. Does a `"none"` grid import need:
   - (a) A user-visible error in the UI ("Free-form designs not supported — convert to HC or SQ first")
   - (b) A silent 400 HTTP error (current behavior)
   - (c) An attempted conversion (out of scope for triage)

---

## Experiment Protocol

### Experiment 9.1 — design.crossovers populated after HC import

**Hypothesis**: After importing a scadnano HC file, `design.crossovers` contains the expected number of crossovers.

**Test Steps**:
1. Use one of the existing test fixtures from `tests/test_scadnano.py` (read the test file to find a HC fixture path)
2. Import via `POST /design/import/scadnano`
3. Check `design.crossovers` length

**Data Collection**:
```bash
# Find the test fixtures
grep -r "scadnano" tests/test_scadnano.py | grep "open\|fixture\|file" | head -10
```
Then:
```bash
curl -X POST http://localhost:8000/api/design/import/scadnano \
  -F "file=@path/to/fixture.sc" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['design']['crossovers']))"
```

**Pass Criteria**: `len(design.crossovers) > 0` AND count matches manual count from the scadnano file's strand domains.

**Fail → Iteration 9.1a**: `import_scadnano()` doesn't construct `Crossover` records from consecutive cross-helix domains. Find the strand domain parsing loop and add crossover detection where `domains[i].helix != domains[i+1].helix`.

**Fail → Iteration 9.1b**: Loopout domains are being incorrectly counted as crossovers. Add a guard: a transition is only a crossover if `domains[i+1]` is a helix domain (not a loopout).

---

### Experiment 9.2 — Square lattice crossover positions match period=12

**Hypothesis**: After importing a scadnano SQ file, crossover positions in `design.crossovers` align with the SQ lattice period=12 constraint.

**Test Steps**:
1. Find or create a scadnano SQ fixture
2. Import and check: for each crossover, verify `half_a.index % 12` falls in the valid SQ crossover slot set (from `crossover_positions.py` SQ constants)

**Data Collection**:
```python
# Python script to validate SQ crossover phases
from backend.core.crossover_positions import SQ_CROSSOVER_POSITIONS  # check actual import path
for xo in design.crossovers:
    assert xo.half_a.index % 12 in SQ_CROSSOVER_POSITIONS, f"Bad index {xo.half_a.index}"
```

**Pass Criteria**: All crossover indices pass the modulo check.

---

### Experiment 9.3 — Loopout domains do not crash crossover rendering

**Hypothesis**: A scadnano file with loopout domains imports without error, and `crossover_connections.js` does not attempt to look up backbone positions for loopout nucleotides (which don't exist in the geometry).

**Test Steps**:
1. Create or find a scadnano fixture with a loopout (strand with `{"loopout": 4}` between two helix domains)
2. Import and load geometry
3. Check console for `[XOVER 3D] unresolved crossover` warnings
4. Check `crossover_connections.js` mesh vertex count

**Pass Criteria**: No unresolved crossover warnings. Loopout is NOT in `design.crossovers`.

**Fail → Iteration 9.3a**: If loopouts appear in `design.crossovers`, `import_scadnano()` is not filtering them. Add a check: only create a `Crossover` when both adjacent domains are helix domains.

---

### Experiment 9.4 — Photoproduct junctions import without crash

**Hypothesis**: A scadnano file with `photoproduct_junctions` imports correctly; junction entries do not interfere with `design.crossovers`.

**Test Steps**:
1. Use the CPD test fixture (check `test_scadnano.py` for a fixture with photoproduct junctions)
2. Import, check no errors
3. Confirm `design.crossovers` count is for actual crossovers, not junctions

**Pass Criteria**: No import errors; `design.crossovers` does not contain junction entries.

---

### Experiment 9.5 — Existing test suite passes

**Test Steps**:
```bash
just test-file tests/test_scadnano.py
```

**Pass Criteria**: All tests pass. For each that fails, determine if failure is due to new `design.crossovers` assertion vs. existing topology logic.

---

### Experiment 9.6 — Round-trip with scadnano

*Note*: NADOC does not currently have a scadnano export — this experiment is aspirational / future-proofing.

**Hypothesis** (discovery only): Determine what would be needed for a round-trip. Examine `export_cadnano()` as a template for what `export_scadnano()` would need to write.

**Test Steps**: Read `export_cadnano()` and note which fields read from `design.crossovers` vs. strand topology. Write a one-paragraph summary of the gap.

**Data Collection**: Written summary appended to this document under a "Round-Trip Notes" section.

---

## Performance Notes

*Do not implement until experiments pass.*

- `_backfill_overhang_sequences()` (called in `crud.py` after import) iterates all strands twice: once to build a `{(helix_id, bp, dir) → base}` lookup, once to apply. This can be one pass.
- `import_scadnano()` uses `_scadnano_xy()` to convert grid positions — this is called per-helix and is already O(n). No action needed.
- Crossover detection added in Iteration 9.1a will be O(sum of domain counts per strand) — already the minimum complexity. No further optimization needed.
- For large designs (500+ strands), the `for strand in design.strands` loop over all strands to find scaffold vs. staple could be pre-indexed by strand type once at import.

---

## Refactor Plan

*Execute only after all 9.x experiments pass.*

1. **Centralize crossover detection**: extract `_detect_crossovers_from_strand_list(strands, helices) → list[Crossover]` — called once from `import_scadnano()`. Handles the loopout guard, dedup, and validation.
2. **Single-pass sequence backfill**: collapse `_backfill_overhang_sequences()` to one dict-build + one application pass.
3. **Add crossover count assertions to existing tests**: mirror the cadnano approach — any test that imports a known file should assert on `len(design.crossovers)`.
4. **Document loopout visual representation**: whatever is decided for clarifying question #1, document the decision and the rendering path in `MAP_RENDERING.md`.
5. **Performance baseline**: record import time before/after for the largest available scadnano fixture.
