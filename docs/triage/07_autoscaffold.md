# Feature 07: Autoscaffold
**Phase**: C (Topology Mutations — requires Phase A + B)

---

## Feature Description

Routes a single scaffold strand through all helices in a design. The scaffold passes between adjacent helices via crossover connections. Post-overhaul, these scaffold crossovers must appear in `Design.crossovers`.

**Key file**: `backend/core/lattice.py`
**Frontend hotkey**: `[1]` = Autoscaffold
**API routes**:
- `POST /design/auto-scaffold` — main entry (modes: `seam_line`, `end_to_end`)
- `POST /design/auto-scaffold-seamless` — single continuous strand
- `POST /design/partition-scaffold` — multi-group partitioning
- `POST /design/jointed-scaffold` — jointed routing (known bugs — see `project_jointed_scaffold.md`)

**Key functions in lattice.py**:
- `auto_scaffold(design, mode, ...)` (line ~2752) — main entry point
- `_helix_adjacency_graph(design)` (line ~?) — builds XY-distance graph
- `_greedy_hamiltonian_path(graph)` — nearest-neighbor path through helices
- `make_nicks_for_autostaple()` (line ~1627) — places nicks at prebreak positions

**User-confirmed**: Scaffold crossovers (helix-to-helix scaffold connections) must be in `Design.crossovers`.

---

## Pre-Condition State

- `auto_scaffold()` existed before `Design.crossovers` was added — likely does NOT write scaffold crossovers to `design.crossovers`
- The scaffold routing creates strand topology (continuous domains) but the crossover records are separate
- `project_jointed_scaffold.md` notes bugs in `auto_scaffold_jointed` — unknown if these were resolved during overhaul
- MAP_SCAFFOLD_ROUTING.md hotkeys confirmed as `[1]` = Autoscaffold, `[2]` = Prebreak — need to verify these still work

---

## Clarifying Questions

1. After autoscaffold runs, should the scaffold's helix-to-helix crossovers be:
   - (a) Automatically added to `design.crossovers` by `auto_scaffold()` itself
   - (b) Added via a subsequent call to `POST /design/crossovers/batch` using the crossover positions implied by scaffold routing
   - (c) Derived on-the-fly from strand topology when reading `design.crossovers` — i.e., scaffold crossovers are not explicitly stored

2. What is the expected visual difference between scaffold crossovers and staple crossovers in `crossover_connections.js`?
   - (a) Same visual (white lines)
   - (b) Scaffold crossovers are scaffold-color (default blue), staple crossovers are white or staple-color
   - (c) Scaffold crossovers are thicker/different line style

3. The `project_jointed_scaffold.md` memory notes "Bug #1+#2 fixed; more bugs reported but not yet described." Are the remaining jointed scaffold bugs a Phase C priority, or deferred?

---

## Experiment Protocol

### Experiment 7.1 — Autoscaffold creates a continuous scaffold strand

**Hypothesis**: `POST /design/auto-scaffold` on a 6HB HC design creates exactly one scaffold strand (or one per Z-segment for disconnected designs) that covers all helices.

**Test Steps**:
1. Load a 6HB design with no scaffold (fresh helices only)
2. `POST /api/design/auto-scaffold` with `{"mode": "seam_line"}`
3. Check: how many scaffold strands? Does each helix have scaffold coverage?

**Data Collection**:
```bash
curl -X POST http://localhost:8000/api/design/auto-scaffold \
  -H 'Content-Type: application/json' -d '{"mode": "seam_line"}' \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
scaffolds = [s for s in d['design']['strands'] if s['strand_type'] == 'scaffold']
print(f'{len(scaffolds)} scaffold strands')
for s in scaffolds:
    total_nt = sum(dom['length'] for dom in s['domains'])
    print(f'  scaffold: {total_nt} nt, {len(s[\"domains\"])} domains')
"
```

**Pass Criteria**: `len(scaffolds) >= 1`; each helix has at least one scaffold domain covering it.

---

### Experiment 7.2 — Scaffold crossovers appear in design.crossovers

**Hypothesis**: After autoscaffold, `design.crossovers` contains entries for each helix-to-helix scaffold connection, matching the scaffold path determined by `_greedy_hamiltonian_path()`.

**Test Steps**:
1. Same as 7.1
2. After autoscaffold, check `design.crossovers` count
3. Check that each crossover's `half_a` and `half_b` are on adjacent helices and at matching bp indices

**Data Collection**:
```bash
# Count crossovers and check helix IDs
... | python3 -c "
xos = d['design']['crossovers']
print(f'{len(xos)} total crossovers')
scaffold_xos = [x for x in xos if x.get('strand_type') == 'scaffold']  # check if typed
print(f'{len(scaffold_xos)} scaffold crossovers')
for x in xos[:3]:
    print(f'  {x[\"half_a\"][\"helix_id\"][:8]} bp={x[\"half_a\"][\"index\"]} ↔ {x[\"half_b\"][\"helix_id\"][:8]} bp={x[\"half_b\"][\"index\"]}')
"
```

**Pass Criteria**: `len(design.crossovers) > 0` AND at least `N-1` crossovers for an N-helix design (one per helix pair in the path).

**Fail → Iteration 7.2a**: If `design.crossovers` is empty after autoscaffold, `auto_scaffold()` doesn't write crossovers. Find where scaffold strand domains are built (near `_build_seam_line_domains` or `_build_end_to_end_domains` in `lattice.py`) and add `Crossover` record construction for each helix transition.

---

### Experiment 7.3 — Scaffold crossover lines visible in 3D

**Hypothesis**: After autoscaffold, the `crossover_connections.js` mesh shows crossover lines between helices for the scaffold path.

**Test Steps**:
1. Run autoscaffold on 6HB
2. Playwright screenshot — should show white lines connecting helix endpoints
3. Check mesh vertex count = `design.crossovers.length * 2`

**Pass Criteria**: Lines visible; vertex count matches.

---

### Experiment 7.4 — Seam line vs. end-to-end modes produce different domain structures

**Hypothesis**: `mode="seam_line"` produces scaffold domains that end near the helix midpoint; `mode="end_to_end"` produces domains that span the full helix length.

**Test Steps**:
1. Autoscaffold with `mode="seam_line"` on a 168bp helix (2× period) — check domain boundaries are near bp 84
2. Autoscaffold with `mode="end_to_end"` — check domain boundaries are at helix ends (bp 0 and bp 167)

**Data Collection**: Domain `bp_start` and `bp_end` for each scaffold domain.

**Pass Criteria**: Seam line domains end within ±7 bp of midpoint; end-to-end domains span full helix.

---

### Experiment 7.5 — Jointed scaffold reproduces or resolves known bugs

**Hypothesis**: `auto_scaffold_jointed` on a multi-cluster design either reproduces the known bugs from `project_jointed_scaffold.md` (documenting them) or they are fixed.

**Test Steps**:
1. Read `project_jointed_scaffold.md` for the Bug #1 scenario
2. Reproduce the exact steps
3. Record: does the bug still occur?

**Data Collection**: Screenshot of the joints panel; console output; `design.crossovers` state after jointed scaffold.

**Pass Criteria (for triage purposes)**: Clear documentation of current state — either "bug reproduced, description added to project_jointed_scaffold.md" or "bug fixed, confirmed passing."

---

### Experiment 7.6 — Scaffold length counter accuracy

**Hypothesis**: After autoscaffold, the scaffold length shown in the UI (Properties panel when scaffold selected) matches the actual nucleotide count from `sum(domain.length for domain in scaffold_strand.domains)`.

**Test Steps**:
1. Autoscaffold on 6HB × 168bp
2. Click scaffold strand in 3D
3. Check Properties panel scaffold length
4. Compute expected length from domain sum

**Pass Criteria**: UI length == domain sum.

---

## Performance Notes

*Do not implement until experiments pass.*

- `_greedy_hamiltonian_path()` is O(n²) in helix count. For n ≤ 48 (typical designs), this takes < 1ms. For multi-origami assemblies with n > 200, this would be slow. Document the n ≤ 48 threshold as a comment. If needed, switch to a KD-tree spatial index for O(n log n).
- `auto_scaffold()` calls `_scaffold_coverage_regions()` which may be a per-helix Python loop. Check if this can be vectorized with `numpy` interval operations.
- Crossover record construction added in Iteration 7.2a should be O(path_length) — acceptable. Pre-allocate the list.
- `make_nicks_for_autostaple()` calls `make_nick()` N times in a loop. Each `make_nick()` call triggers a full `Design(...)` rebuild. Consider batching: collect all nick positions first, then apply in one `Design(...)` rebuild.

---

## Refactor Plan

*Execute only after all 7.x experiments pass.*

1. **Add crossover registration to autoscaffold path**: wherever `auto_scaffold()` determines that the scaffold transitions from helix A to helix B, construct and append a `Crossover(half_a=HalfCrossover(helix_id=A, ...), half_b=...)` to the design's crossover list.
2. **Batch nick application**: collect all nick positions from `make_nicks_for_autostaple()` and apply them in a single `Design(...)` rebuild rather than N sequential rebuilds.
3. **Document n ≤ 48 threshold**: add a comment to `_greedy_hamiltonian_path()` noting the complexity class and the threshold.
4. **Update `project_jointed_scaffold.md`**: add findings from Experiment 7.5 to the project memory file.
5. **Performance baseline**: record `auto_scaffold()` time on 26HB vs. 96HB fixtures before and after refactoring.
