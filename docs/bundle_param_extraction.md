# Bundle Inter-Helix Stiffness Parameter Extraction

Extracts 6-DOF inter-helix stiffness matrices from a GROMACS production trajectory
for use in coarse-grained (mrdna/ARBD) parameterization of DNA origami bundles.

## Script

```
runs/10hb_bundle_params/extract_bundle_params.py
```

## Usage

```bash
cd runs/10hb_bundle_params
python3 extract_bundle_params.py \
    --run-dir nominal \
    --skip 5 \          # every 5th frame = 0.5 ns sampling
    --out-dir nominal   # writes all_pairs.json + context_params.json
```

## What it computes

For each neighboring helix pair defined in `_HELIX_NEIGHBOR_PAIRS`, the script computes
a 6-DOF inter-helix coordinate per frame:

| DOF | Symbol | Physical meaning |
|-----|--------|-----------------|
| q0 | axial sep | separation along helix A axis (Å) |
| q1 | lateral 1 | separation in perp dir 1 (Å) |
| q2 | lateral 2 | separation in perp dir 2 (Å) |
| q3 | Euler α | in-plane rotation (rad) |
| q4 | Euler β | inter-helix tilt angle (rad) |
| q5 | Euler γ | out-of-plane twist (rad) |

Stiffness matrix: **K = kT × Cov⁻¹** (Boltzmann inversion, kT = 2.579 kJ/mol at 310 K).

Pairs are grouped by neighbor-count context:
- `2-2`: both helices have 2 nearest neighbors (edge helices)
- `2-3`: one helix has 2 neighbors, the other has 3 (junction)
- `3-3`: both helices have 3 nearest neighbors (internal pair)

## Trajectory selection (automatic)

Priority order used at load time:
1. `view_whole.xtc` — PBC-preprocessed with `gmx trjconv -pbc whole`; recommended
2. All `prod_best.part*.xtc` files in sorted order (concatenated automatically)
3. `prod.xtc` — fallback for short/benchmark runs

Topology: `em.tpr` > `prod_best.tpr` > `prod.tpr` > `npt.gro`

## Residue-to-helix assignment

Uses **topology-based** assignment via `build_p_gro_order` from
`backend/core/atomistic_to_nadoc.py`. GROMACS preserves the atom order from
`pdb2gmx` (which reads `input_nadoc.pdb`), so the i-th P atom in any GROMACS
file corresponds exactly to the i-th entry in `p_order` — no geometry search
needed.

Requires `input_nadoc.pdb` to be present in the run directory.

### Why not geometry-based nearest-axis?

Geometry-based assignment (nearest helix axis by perpendicular distance) fails for
two reasons after tens of ns of MD:
1. **Translational drift**: the structure sits at an arbitrary GROMACS box offset
   (not at the design origin).
2. **Rotational diffusion**: the bundle rotates in XY over time; outer helices
   (40 Å from centroid) can displace > 10 Å after a 15° rotation, causing
   mis-assignment.

The topology-based approach is immune to both.

## Known limitations

### 1. Crossover centroid bias

Several pairs report lateral separation (lat) ≈ 6–11 Å instead of the expected
~22 Å for B-form DNA. The cause: crossover residues physically sit at the midpoint
between two helix axes. Including them in the C1' centroid computation pulls each
helix's PCA origin toward the other, halving the apparent separation.

**Affected pairs**: those with many shared crossovers (especially `3-3` and
pairs on the same X column in the honeycomb lattice).

**Workaround**: K values from affected pairs are unreliable. Only trust pairs
with `lat > 12 Å` (see `all_pairs.json`, `q_mean_physical.lateral_sep_A`).

**Fix (not yet implemented)**: exclude crossover bp positions from the centroid
when computing the helix axis origin in `_interhelix_q`.

### 2. Euler ZYZ gimbal lock

`K_q3` and `K_q5` (in-plane rotation α and twist γ) are unreliable for all pairs
with tilt β < 15°. Near β = 0°, α and γ become degenerate (gimbal lock), so their
variance collapses to near-zero, yielding spuriously large apparent stiffness
(10,000–35,000 kJ/mol/rad²). Ignore these values.

**Reliable DOFs**: q1, q2 (lateral stiffness) and q4 (tilt stiffness).

**Fix (not yet implemented)**: replace Euler ZYZ rotational parameterization with
axis-angle or quaternion representation, which avoids singularities near the
identity rotation.

### 3. `3-3` context (h_XY_1_1 ↔ h_XY_0_1): not extractable yet

This pair is affected by both crossover bias (lat ≈ 8 Å) and the gimbal lock.
No reliable stiffness values can be extracted until the crossover-bp exclusion
is implemented.

## Convergence requirements

The per-pair ESS (effective sample size) at 500 ps sampling:

| Condition | ESS target | Data needed per pair |
|-----------|-----------|---------------------|
| 10% relative uncertainty | ≥ 100 | ~50 ns |
| 5% relative uncertainty | ≥ 400 | ~200 ns |
| Full monitor_convergence.py threshold | ≥ 200 | ~100 ns |

At 100 ps/frame (`nstxout-compressed = 50000`, `dt = 0.002 ps`), with `skip = 5`
(500 ps effective sampling), and autocorrelation time τ ≈ 0.3–0.5 ns:

- ESS ≈ T_total / (2τ) ≈ 100 ns / 0.8 ns ≈ 125 per pair
- Context-level pooling: 3–6 pairs per context → multiply per-pair ESS

## First-pass results (10hb nominal run, 54.6 ns view_whole.xtc)

Run on 2026-04-26. Reliable pairs only (lat > 12 Å):

| Context | n_pairs | K_lateral (kJ/mol/Å²) | K_tilt (kJ/mol/rad²) | ESS_lat |
|---------|---------|----------------------|----------------------|---------|
| 2-2 | 3 of 6 | 0.18 ± 0.10 | 100–480 | 49–59 |
| 2-3 | 2 of 4 | 0.19 ± 0.05 | 230–390 | 50–55 |
| 3-3 | 0 of 1 | not extractable | not extractable | — |

The high variance in K_tilt (4×) across pairs of the same context type suggests
either genuine structural asymmetry (different crossover configurations per site)
or insufficient sampling of slow bending modes. More runtime needed.

**Run status as of 2026-04-26**: 103.4 ns completed (10.3% of 1000 ns target).
Run is active (PID 997601). The full 1000 ns target is appropriate; targeting
~220+ ns in `view_whole.xtc` before re-running extraction for converged lateral
stiffness values.

## Output files

| File | Contents |
|------|---------|
| `nominal/all_pairs.json` | Per-pair q_mean, q_std, stiffness matrix, ESS, block SEM |
| `nominal/context_params.json` | Pooled context-level stiffness + ESS |
| `nominal/convergence.png` | Thermodynamic convergence panels (6 observables) |

## Extending view_whole.xtc for late frames

Current `view_whole.xtc` covers 0–54.6 ns (547 frames). To extend after more
production data accumulates:

```bash
cd runs/10hb_bundle_params/nominal
gmx trjcat -f prod_best.part0002.xtc prod_best.part0003.xtc -o prod_cat.xtc
gmx trjconv -f prod_cat.xtc -s em.tpr -pbc whole -o view_whole.xtc
```

After extending, re-run `check_progress.py` to update `convergence.png`, then
re-run `extract_bundle_params.py` to update `all_pairs.json`.
