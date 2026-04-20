# Feature 06: Prebreak + Autocrossover
**Phase**: C (Topology Mutations — requires Phase A + B)

---

## Feature Description

Two related crossover operations:

**Prebreak**: Nicks all staples at canonical crossover positions (the positions where DX crossovers would be placed). Produces a design with many short staple fragments ready for crossover routing. API: `POST /design/prebreak`

**Autocrossover**: Adds all valid crossover sites to `design.crossovers` in one batch. Previously this was driven by the deleted `crossover_locations.js` overlay. Now it should use `crossover_positions.py::all_valid_crossover_sites()`.

**User-confirmed decisions**:
- Both scaffold AND staple crossovers go in `design.crossovers`
- Valid crossover sites must be shown as an interactive 3D overlay in the 3D viewport (replacement for `crossover_locations.js`) AND in the 2D cadnano editor

**Key backend files**:
- `backend/core/crossover_positions.py` — `all_valid_crossover_sites()`, `validate_crossover()`
- `backend/core/lattice.py` — `make_nicks_for_autostaple()` (line ~1627)

**Key API routes**:
- `GET /design/crossovers/valid` — returns all valid sites
- `POST /design/crossovers` — add one crossover
- `POST /design/prebreak` — nick staples at prebreak positions

---

## Pre-Condition State

- `crossover_locations.js` is **deleted** — the 3D interactive valid-site overlay no longer exists
- No e2e test covers the prebreak → crossover placement workflow
- `crud.py:1787` has `TODO: DELETE — add_crossover calls _splice_strands_for_crossover` — stale old crossover code may fire on `POST /design/crossovers` and corrupt strand topology
- The 2D cadnano editor (`cadnano-editor/api.js:104`) has `TODO: DELETE — addCrossover calls POST /design/crossovers` — may be using correct new route or may have stale logic
- Unknown: does `POST /design/crossovers` currently populate `design.crossovers`, or does it only splice strands (old behavior)?

---

## Clarifying Questions

1. **"Autocrossover" definition**: post-overhaul, which meaning is correct?
   - (a) Add ALL valid sites from `GET /design/crossovers/valid` to `design.crossovers` in one batch call — no strand topology changes; crossovers are just connection records
   - (b) The old behavior: add crossovers AND split/join staple strand domains at each crossover site (topology mutation)
   - (c) Something else — e.g., autocrossover only adds crossovers at specific positions based on staple routing algorithm

2. Should prebreak and autocrossover be accessible from:
   - (a) Both the 3D main view and the 2D cadnano editor
   - (b) 3D main view only (keys `[2]` for prebreak, new hotkey for autocrossover)
   - (c) 2D cadnano editor only (as toolbar buttons in pathview)

3. For the **3D valid-site overlay** (replacement for `crossover_locations.js`):
   - What did `crossover_locations.js` look like visually? (Run `git show HEAD~N:frontend/src/scene/crossover_locations.js` to recover it)
   - Should hovering a valid site show a preview of the crossover line?
   - Should clicking a valid site add it to `design.crossovers` immediately?

---

## Experiment Protocol

### Experiment 6.1 — GET /design/crossovers/valid returns correct sites

**Hypothesis**: On a 6HB HC design, `GET /design/crossovers/valid` returns sites that match the HC lattice period=21 crossover positions.

**Test Steps**:
1. Load `multi_domain_test.nadoc` (known 6HB or similar)
2. `GET /api/design/crossovers/valid`
3. Count sites and check bp indices modulo 21

**Data Collection**:
```bash
curl http://localhost:8000/api/design/crossovers/valid \
  | python3 -c "
import sys, json
sites = json.load(sys.stdin)
print(f'{len(sites)} valid sites')
# Check period-21 alignment
indices = [s['index'] % 21 for s in sites]
print('index mod 21 distribution:', sorted(set(indices)))
"
```

**Pass Criteria**: At least one valid site; all `index % 21` values are in the expected HC crossover slot set (from `crossover_positions.py` HC constants table).

**Fail → Iteration 6.1a**: If 0 sites returned, check whether the design has adjacent helices in the lattice. The endpoint may require helices to be in valid neighboring cells.

**Fail → Iteration 6.1b**: If indices are wrong, the HC crossover table in `crossover_positions.py` has the wrong offset. Cross-reference with `REFERENCE_CONSTANTS.md`.

---

### Experiment 6.2 — POST /design/crossovers adds to design.crossovers

**Hypothesis**: Calling `POST /design/crossovers` with a valid crossover body adds exactly one entry to `design.crossovers` and does NOT duplicate the entry on subsequent calls to GET.

**Test Steps**:
1. Load design, record `len(design.crossovers)` = N
2. Get one valid site from `GET /design/crossovers/valid`
3. `POST /design/crossovers` with `{half_a: {...}, half_b: {...}}`
4. Check `len(design.crossovers)` = N+1

**Data Collection**: Response body from POST; subsequent GET /design to check crossover list.

**Pass Criteria**: `len(design.crossovers)` increases by exactly 1. No strand topology corruption (all strand domains still valid).

**Fail → Iteration 6.2a**: If `len` doesn't change, the POST handler is not writing to `design.crossovers`. Check `crud.py::add_crossover()` — it may only call `_splice_strands_for_crossover()` (old behavior) without adding to `design.crossovers`.

**Fail → Iteration 6.2b**: If strand domains are corrupted, `_splice_strands_for_crossover` (marked for deletion in `crud.py:1787`) is still being called. Remove that call first, then re-test.

---

### Experiment 6.3 — DELETE /design/crossovers/{id} removes from design.crossovers

**Hypothesis**: After adding a crossover (Exp 6.2), deleting it by ID restores `design.crossovers` to its original count.

**Test Steps**:
1. Add crossover (Exp 6.2), record ID from response
2. `DELETE /api/design/crossovers/{id}`
3. Check `len(design.crossovers)` = N (original)

**Pass Criteria**: Count returns to N. No dangling references in strand topology.

---

### Experiment 6.4 — Prebreak places nicks at valid crossover positions

**Hypothesis**: `POST /design/prebreak` on a design with a scaffold strand places nicks in the scaffold (or staples?) at positions that correspond to the valid crossover site indices.

**Test Steps**:
1. Load a 6HB design with scaffold and staples
2. `POST /design/prebreak`
3. Check: for each nick added, is the nick position in the valid crossover sites set?

**Data Collection**:
```python
# Compare nick positions to valid crossover sites
valid_indices = {s['index'] for s in valid_sites}
for strand in design.strands:
    for domain in strand.domains:
        # nicks are at domain boundaries — check if boundary bp is in valid_indices
        assert domain.bp_start in valid_indices or domain.bp_end in valid_indices
```

**Pass Criteria**: All nick positions correspond to valid crossover bp indices.

**Fail → Iteration 6.4a**: Prebreak endpoint uses hardcoded positions instead of `crossover_positions.py::all_valid_crossover_sites()`. Refactor to use the shared function.

---

### Experiment 6.5 — 3D overlay discovery (git history)

**Hypothesis**: Recovering the deleted `crossover_locations.js` reveals what the 3D valid-site overlay looked like and what it needs to be rebuilt as.

**Test Steps**:
```bash
# Find the commit that deleted the file
git log --oneline -- frontend/src/scene/crossover_locations.js

# Read the file as it was before deletion
git show <hash>^:frontend/src/scene/crossover_locations.js > /tmp/crossover_locations_recovered.js
```

**Data Collection**: Copy of the recovered file. Document:
- What geometry it used (dots? lines? spheres?)
- What data it consumed (old crossover model vs. new)
- How clicks were handled
- How it was integrated into `design_renderer.js`

**Pass Criteria**: A written "Rebuild Spec" section appended to this document describing exactly what to rebuild.

---

### Experiment 6.6 — 2D editor crossover placement (Phase 1 scope)

**Hypothesis**: In the 2D cadnano editor, clicking on a valid crossover site adds it to `design.crossovers` and the BroadcastChannel update causes the 3D view to show the new crossover line.

**Test Steps**:
1. Open `/cadnano` in a second browser tab
2. Open the 3D main view in the first tab
3. In the 2D editor pathview, identify a valid crossover site (may need to be visually marked by the editor)
4. Click the site
5. Verify: 3D view updates to show a new crossover line

**Data Collection**: Console logs from BroadcastChannel in both tabs; `design.crossovers` count before/after.

**Pass Criteria**: `design.crossovers` count increases by 1; 3D view shows new line within 1 second of click.

**Fail → Iteration 6.6a**: If BroadcastChannel doesn't propagate, check `nadocBroadcast.emit('design-changed')` is called in `cadnano-editor/api.js::mutate()`.

---

## Performance Notes

*Do not implement until experiments pass.*

- `all_valid_crossover_sites(design)` in `crossover_positions.py` — if it iterates all helix pairs × all bp positions using Python loops, this could be slow for large designs. Target: full NumPy vectorization using `np.arange` for bp index arrays and `np.isin` for slot membership test.
- `POST /design/crossovers` (batch) — currently appears to be single-crossover-only. For autocrossover (add all valid sites), implement a `POST /design/crossovers/batch` endpoint that adds all in one transaction (one `set_design()` call, not N calls).
- The 3D valid-site overlay should use `THREE.InstancedMesh` (not N individual objects) for large designs with 1000+ valid sites.

---

## Rebuild Spec for 3D Valid-Site Overlay

*(Fill in after Experiment 6.5 recovers the deleted file)*

**File to create**: `frontend/src/scene/crossover_locations.js` (or `valid_crossover_overlay.js`)

**Data source**: `GET /design/crossovers/valid` response — array of `{helix_id, index, strand, neighbor_helix_id}` objects

**Geometry**: TBD after Exp 6.5

**Interaction**: Click adds crossover → `POST /design/crossovers`; hover shows preview line

**Integration point**: Called from `design_renderer.js::rebuild()` after `buildCrossoverConnections()`

---

## Refactor Plan

*Execute only after all 6.x experiments pass.*

1. **Remove dead code**: delete `_splice_strands_for_crossover` from `crud.py` (lines ~1616, ~1787 — marked `TODO: DELETE`).
2. **Batch crossover endpoint**: `POST /design/crossovers/batch` accepting a list of `{half_a, half_b}` objects — single backend transaction for autocrossover.
3. **Vectorize `all_valid_crossover_sites()`**: replace per-helix-pair Python loop with NumPy array operations.
4. **Add prebreak/autocrossover e2e test**: `frontend/e2e/triage/exp_06_prebreak_autocrossover.spec.js`.
5. **Performance baseline**: record time for autocrossover on 26HB fixture.
