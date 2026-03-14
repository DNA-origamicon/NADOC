# NADOC Validation Experiments

Systematic validation of XPBD simulation (exp01–04) and autostaple algorithm (exp05–08).
Run from the repo root with:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run python experiments/expXX_name/run.py
```

Each experiment produces `results/` with PNG figures and `metrics.json`.

---

## Experiment summary

| # | Name | Status | Key finding |
|---|------|--------|-------------|
| 01 | Bond integrity | ✅ PASS | Constraint solver correct — max deviation 0.0024 nm after ±0.5 nm perturbation |
| 02 | Thermal stability | ✅ PASS | RMSD bounded at all noise levels; helix stays helical |
| 03 | Excluded volume | ⚠️ PARTIAL | EV reliable at noise ≤ 0.06 nm/substep; transient violations at high noise |
| 04 | Crossover geometry | ✅ PASS | Crossover region 1.27× stiffer than free ends (after bug fix) |
| 05 | Staple length distribution | ✅ PASS (diagnosed) | Autostaple alone: 5–40% strands in range; root cause: no nick placement + min_end_margin too small |
| 06 | Exclusion zone | ✅ PASS | No scaffold-staple exclusion violations in fresh bundle (scaffold crossovers absent) |
| 07 | Nick placement algorithm | ✅ PASS | 100% of strands in 18–50 nt window with min_end_margin=9 + greedy nick algorithm |
| 08 | Real-time performance | ✅ PASS | 18HB 126bp: 7ms total — 14× faster than 100ms RT threshold; real-time feasible |

---

## Bugs found and fixed

### Bug 1: Static EV neighbour list (exp03)
**File**: `backend/physics/xpbd.py`
**Problem**: The excluded-volume neighbour list was built once at construction
time and never updated. Under thermal noise, beads drifted outside the initial
cutoff, allowing helix interpenetration.
**Fix**: `_rebuild_excl_ij_inplace(sim)` called every `ev_rebuild_interval`
(default 5) steps. `EV_NEIGHBOUR_CUTOFF = 2.0 nm` (fixed) keeps all
adjacent-helix pairs tracked regardless of thermal drift.

### Bug 2: Crossover bond rest length (exp04)
**File**: `backend/physics/xpbd.py`
**Problem**: Cross-helix backbone bonds used the actual geometric distance
(~4 nm) as rest length → zero restoring force → crossover region paradoxically
more mobile than free ends.
**Fix**: Cross-helix bonds now use `BACKBONE_BOND_LENGTH` (0.678 nm) as rest
length. Creates realistic tension pulling adjacent helices together.

### Fix 3: EV distance tuning (exp03)
`EXCLUDED_VOLUME_DIST`: 0.6 nm → 0.3 nm. At 2.25 nm lattice spacing, adjacent
helix beads can approach 0.25 nm; the 0.6 nm threshold created artificial
tension in the initial geometry.

### Fix 4: 2nd-neighbor bonds skip helix boundaries
Bending stiffness (i↔i+2) now only applies within a single helix. Cross-helix
bending bonds are not physically meaningful.

---

## Comparison with oxDNA expectations

| Property | oxDNA (literature) | XPBD (after fixes) | Match? |
|----------|-------------------|---------------------|--------|
| Backbone bond rest | ~0.66 nm | 0.678 nm | ✅ Close |
| Crossover stiffer than free | Yes | 1.27× | ✅ Yes |
| Adjacent helix non-penetration | Always | Reliable at noise ≤ 0.06 | ⚠️ Mostly |
| Thermal amplitude at 300K | ~0.3–0.5 nm RMSD | 0.44 nm at noise=0.01 | ✅ Reasonable |

oxDNA binary not installed. Install with:
```bash
conda install -c bioconda oxdna
# or build from source: https://github.com/lorenzo-rovigatti/oxDNA
```

---

## Recommended slider defaults

| Parameter | Recommended | Notes |
|-----------|-------------|-------|
| Thermal noise | 0.01–0.04 nm/substep | Above 0.06 shows EV artifacts on multi-helix |
| Bond stiffness | 1.0 | Lower → floppy backbone |
| Bending stiffness | 0.3 | Key for rod-like helices |
| Base-pair stiffness | 0.5 | Maintains cross-section |

---

## Autostaple bugs found and fixed (exp05–08)

### Bug 1: `min_end_margin=3` produces tiny stub strands
**File**: `backend/core/lattice.py`
**Problem**: Crossovers at bp 3–5 produce outer stubs of 2×(3+1)=8 nt — below the 18 nt
minimum for a thermodynamically stable staple.
**Fix**: `min_end_margin` default changed 3 → **9** in `compute_autostaple_plan` and
`make_autostaple`. At bp=9 the minimum outer stub is 2×10=20 nt. ✓

### Bug 2: Nick placement (Stage 2) was missing
**File**: `backend/core/lattice.py`
**Problem**: `make_autostaple` only placed crossovers. The resulting zigzag strands
spanned entire helices (22–504 nt depending on length), far exceeding the 50 nt max.
**Fix**: Added `make_nicks_for_autostaple(design, target_length=30, min_length=18, max_length=50)`.
`/design/autostaple` endpoint now runs BOTH stages. 100% of strands in 18–50 nt.

---

## Autostaple algorithm architecture (final)

**Stage 1**: `make_autostaple(design)` — places crossovers
- Greedy global selection: all valid in-register candidates, sorted by bp
- `min_pair_spacing=21` (one full twist period), `min_helix_spacing=7`
- `min_end_margin=9` (ensures stubs >= 18 nt)

**Stage 2**: `make_nicks_for_autostaple(design)` — adds nicks
- Walks each strand 5'→3' as flat nucleotide list
- Greedy nicks every 30 nt, stops when remaining ≤ 50 nt
- Never creates segments < 18 nt
- Nicks applied right-to-left (original strand ID preserved throughout)

---

## Next steps

**Physics (exp01–04)**:
1. **Angular constraints** between consecutive bonds to model persistence length.
2. **Cell-list EV** for designs > 500 particles (current O(N²) rebuild will lag).
3. **oxDNA V5.2 comparison** once binary is installed.

**Autostaple (exp05–08)**:
1. **Real-time trigger**: debounce autostaple on every design edit (~50ms delay → total ≤ 70ms).
2. **Cache-aware plan**: only recompute crossover plan when helix set changes; reuse plan on
   strand-only edits (nick/crossover placements).
3. **Staple length parameter UI**: expose `target_length` slider (default 30) and `min_length`
   (default 18) in the right panel for expert users.
4. **Test with full scaffold routing**: once scaffold crossovers are placed between helices,
   test that staple autostaple correctly respects the 5 bp exclusion zone.
