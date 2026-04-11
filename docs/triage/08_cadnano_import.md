# Feature 08: cadnano Import
**Phase**: A (Foundation)

---

## Feature Description

Imports caDNAno v2 JSON files into NADOC `Design` objects.

**Key file**: `backend/core/cadnano.py::import_cadnano()`
**API route**: `POST /api/design/import/cadnano`
**Test file**: `tests/test_cadnano.py` (17 tests)

### caDNAno v2 Format
The format represents strands as per-helix linked-lists:
```json
{
  "vstrands": [
    {
      "row": 0, "col": 1, "num": 0,
      "scaf": [[prev_helix, prev_bp, next_helix, next_bp], ...],
      "stap": [[prev_helix, prev_bp, next_helix, next_bp], ...],
      "skip": [...],  // -1 = deletion
      "loop": [...]   // +n = insertion
    }
  ]
}
```

A crossover in caDNAno is encoded as a linked-list entry where `next_helix != current_helix` — meaning the strand continues on a different helix at the same bp index.

**Post-overhaul requirement (user-confirmed)**: Both scaffold AND staple crossovers must appear in `Design.crossovers` after import.

---

## Pre-Condition State

- 17 existing tests in `test_cadnano.py` — unknown if any assert `design.crossovers` is populated
- `import_cadnano()` was written before `Design.crossovers` existed in the model; likely does NOT populate it
- Round-trip export: if `export_cadnano()` reads strand topology (not `design.crossovers`) it may still work, but `design.crossovers` would be empty on reload
- `crud.py:1787` has `TODO: DELETE — add_crossover calls _splice_strands_for_crossover` — stale crossover code may interfere

---

## Clarifying Questions

1. The caDNAno linked-list encodes a crossover as `next_helix != current_helix` at a given bp. Does the importer need to call `make_staple_crossover()` / `lattice.py` logic to populate `design.crossovers`, or should it directly construct `Crossover(half_a=..., half_b=...)` records?

   **Why this matters**: `make_staple_crossover()` also modifies strand topology (splits domains). If the importer already sets up correct strand topology, calling it again would corrupt the design. Conversely, directly constructing `Crossover` records skips validation.

2. For **half-crossovers** (one side of a DX motif where the other helix doesn't exist — effectively a blunt end in caDNAno's `[−1, −1, −1, −1]` pattern): should these be stored in `design.crossovers` or left out?

3. After import, `autodetect_all_overhangs()` is called. Does this need to run **before** or **after** `design.crossovers` is populated?

---

## Experiment Protocol

### Experiment 8.1 — design.crossovers populated after import

**Hypothesis**: After importing `3NN_ground truth.nadoc`, `design.crossovers` contains a non-zero number of entries corresponding to the 3NN motif crossovers.

**Test Steps**:
1. Load `Examples/3NN_ground truth.nadoc` (or POST to `/design/import/cadnano`)
2. Check `design.crossovers` length

**Expected crossover count**: For a 3NN structure, estimate from the design's helix pair count × crossovers per pair. Look up the specific count from the `.nadoc` file's known topology.

**Data Collection**:
```bash
curl -X POST http://localhost:8000/api/design/load \
  -H 'Content-Type: application/json' \
  -d '{"path": "Examples/3NN_ground truth.nadoc"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); xos=d['design']['crossovers']; print(f'{len(xos)} crossovers')"
```

**Pass Criteria**: `len(design.crossovers) > 0` AND count matches expected count from manual inspection of the .nadoc file.

**Fail → Iteration 8.1a**: If `design.crossovers` is empty, `import_cadnano()` does not populate it. Find the linked-list traversal in `_trace_strand()` (line ~269) where `next_helix != current_helix` transitions are detected, and add `Crossover` record construction there.

**Fail → Iteration 8.1b**: If count is wrong (too few), check whether scaffold crossovers are being registered separately from staple crossovers. Both must be included.

---

### Experiment 8.2 — 3D render shows crossover lines after import

**Hypothesis**: After importing `26hb_platform_v3.nadoc`, the 3D viewport shows white crossover connection lines between all helix pairs that have crossovers.

**Test Steps**:
1. Load `26hb_platform_v3.nadoc`
2. Wait for geometry to load
3. Playwright screenshot

**Data Collection**:
```javascript
const xoCount = await page.evaluate(() =>
  window._nadoc?.store?.getState()?.currentDesign?.crossovers?.length ?? -1
)
const meshVerts = await page.evaluate(() => {
  const m = window._nadoc?.scene?.getObjectByName('crossoverConnections')
  return m?.geometry?.attributes?.position?.count ?? -1
})
// Expected: meshVerts === xoCount * 2
```

**Pass Criteria**: Screenshot shows visible crossover lines; `meshVerts === xoCount * 2`.

---

### Experiment 8.3 — Round-trip preserves crossover count

**Hypothesis**: `import → export cadnano JSON → re-import` yields the same `design.crossovers` count.

**Test Steps**:
1. Load `3NN_ground truth.nadoc` → record `xoCount1`
2. `GET /design/export/cadnano` → save to `/tmp/rt_test.json`
3. `POST /design/import/cadnano` with the saved file → record `xoCount2`
4. Assert `xoCount1 == xoCount2`

**Pass Criteria**: Equal counts. Optionally verify crossover IDs differ but `(helix_id, index, strand)` tuples match.

**Fail → Iteration 8.3a**: If `xoCount2 < xoCount1`, `export_cadnano()` does not write some crossovers back into the linked-list format. Check `export_cadnano()` for reliance on strand topology rather than `design.crossovers`.

---

### Experiment 8.4 — Existing test suite still passes

**Hypothesis**: All 17 tests in `test_cadnano.py` pass without modification.

**Test Steps**:
```bash
just test-file tests/test_cadnano.py
```

**Pass Criteria**: 17/17 pass.

**Fail → Iteration 8.4a**: For each failing test, determine if it fails because `design.crossovers` is now expected to be non-empty but the test fixture produces an empty list, or because new crossover construction broke existing assertions. Fix the assertion, not the logic.

---

### Experiment 8.5 — Half-crossover handling (discovery)

**Hypothesis**: Determine whether blunt-end entries in caDNAno format are being imported as crossovers or ignored.

**Test Steps**:
1. Find or construct a minimal `.json` file with one helix that has a `[-1,-1,-1,-1]` terminal strand entry (blunt end)
2. Import it and check `design.crossovers`

**Data Collection**: Log all `Crossover` records; note if any have `half_b.helix_id` pointing to a non-existent helix.

**Pass Criteria**: Blunt ends do NOT appear in `design.crossovers` (they are not DX crossovers). Document this behavior as the defined rule.

---

## Performance Notes

*Do not implement until experiments pass.*

- `_trace_strand()` walks the linked-list O(n) per strand. Currently iterates `[prev, prev_bp, next, next_bp]` entries by following linked-list pointers. Building a dict `{(helix_num, bp_index) → vstrand_entry}` first would reduce lookup from O(n) to O(1) per step.
- `import_cadnano()` calls `autodetect_all_overhangs()` which is O(helices × bp_range). For large designs (96HB+), this dominates import time. Could be parallelized per-helix with `concurrent.futures` if Python GIL allows it (check: all numpy operations).
- If `Crossover` construction is added to the import path, pre-allocate the crossover list with a size estimate to avoid repeated list appends.

---

## Refactor Plan

*Execute only after all 8.x experiments pass.*

1. **Centralize crossover detection**: extract a helper `_detect_crossovers_from_linked_list(vstrands) → list[Crossover]` that is called once from `import_cadnano()`. This makes the crossover extraction auditable and testable in isolation.
2. **Dedup scaffold vs. staple crossovers**: since scaffold and staple are separate arrays in caDNAno but may cross the same bp positions, add dedup logic — a crossover registered from the scaffold array should not be re-registered from the staple array at the same site.
3. **Add crossover assertions to existing tests**: for each test in `test_cadnano.py` that imports a file with known topology, add an assertion on `len(design.crossovers)`. This prevents regression.
4. **Performance baseline**: record import time before/after for `26hb_platform_v3.nadoc`.
