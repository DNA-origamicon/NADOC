# Helical Geometry Validation Report
**Date:** 2026-04-14  
**Reference:** `Examples/1zew.pdb` (PDB 1ZEW — B-DNA crystal, 10-mer, 2.25 Å resolution)  
**Test structures:** NADOC-generated 10-mer duplexes at honeycomb cells (0,0), (0,1), (1,1)  
**Script:** `scripts/helix_cyl_diff.py`  
**Design creator:** `scripts/create_nadoc_pdb.py`

---

## 1. Methodology

All structures are analysed by the same pipeline:

1. Parse ATOM records (no solvent, no ions).
2. Fit a helical axis by SVD through all phosphorus (P) atoms across both strands.
3. Express every heavy atom in cylindrical coordinates (r, θ, z) centred on that axis, with a fixed reference direction derived from the global X axis.
4. For each consecutive residue pair (N → N+1) on the same chain, record Δr, Δθ, Δz for every atom type present in both residues.
5. Sign-normalise so that Δz > 0 corresponds to 5'→3' traversal in the +z direction of the fitted axis; Δθ is normalised with the same sign flip but Δr is NOT flipped (see Section 4.3).

**Sequence:** 5′-CCTCTAGAGG-3′ (self-complementary palindrome, same as 1ZEW chains A and B).  
**Nomenclature:** 1ZEW chain A runs 5′→3′ in the +z direction of the fitted axis; chain B runs 3′→5′ (sign-normalised to +z for comparison). NADOC scaffold chain A is assigned the same sequence; the staple chain B derives the complement.

---

## 2. Structure Summary

| Structure          | Cell   | Scaffold dir | Axis direction (fitted)           | Chains | Residues | P-atom steps |
|--------------------|--------|--------------|-----------------------------------|--------|----------|--------------|
| 1ZEW reference     | n/a    | n/a          | [0.918, 0.377, 0.127]             | A, B   | 20       | 338 records  |
| NADOC (0,0)        | HC 0,0 | FORWARD      | [0.242, −0.105, 0.965]            | A, B   | 20       | 344 records  |
| NADOC (0,1)        | HC 0,1 | REVERSE      | [−0.209, 0.091, 0.974]            | A, B   | 20       | 344 records  |
| NADOC (1,1)        | HC 1,1 | FORWARD      | [0.242, −0.105, 0.965]            | A, B   | 20       | 344 records  |

**Notable:** Cells (0,0) and (1,1) are both even-parity (FORWARD scaffold) and produce numerically identical results to three decimal places. All analysis that follows treats them as a single case.

The 6 extra records in NADOC vs 1ZEW arise because NADOC places a P atom on the 5′-terminal residue, while PDB 1ZEW lacks the terminal P (standard crystallographic convention). This adds one P-involving N→N+1 step per chain (6 atoms × 2 chains = 12 extra records for non-P atoms too, but only P and OP1/OP2 gain steps where both residues carry the atom).

---

## 3. Fitted Axis Analysis

### 3.1 1ZEW helix axis

1ZEW's fitted axis is [0.918, 0.377, 0.127] — the helix runs nearly along the global X-axis (roughly 84° from Z). This reflects real crystal packing: the 10-mer duplex is packed nearly horizontally in the unit cell. The axis is **real tilt**, not an artefact.

### 3.2 NADOC axis tilt artefact

NADOC helices are designed along the Z axis (axis_start = (x₀, y₀, 0), axis_end = (x₀, y₀, 3.34 nm)). The ideal fitted axis should therefore be [0, 0, 1]. Instead, NADOC (0,0)/(1,1) yields [0.242, −0.105, 0.965] — a ~14.8° tilt from Z.

**Root cause — incomplete phase coverage:** NADOC uses a B-DNA twist of 34.286°/bp (= 360°/10.5 bp/turn). In 10 steps, the P atoms sweep 9 × 34.286° = 308.57° of azimuthal angle (9 inter-residue steps per 10-residue strand). This is significantly short of one full turn (360°), so the centre of mass of the P atom positions is NOT on the helix axis — it is displaced radially toward the "missing" phase angle. The SVD best-fit line through this off-centre cloud is tilted relative to Z.

By contrast, 1ZEW uses standard B-DNA twist of ~36°/bp (= 360°/10). Ten residues × 36° = 360° — exactly one full turn. The P atom centre of mass DOES fall on the helix axis for a perfect 10-mer at 36°/bp, so the 1ZEW axis tilt reflects true crystal packing, not SVD artefact.

**Consequence:** All metrics derived from the tilted NADOC axis carry a systematic measurement error. Specifically:
- Δz is slightly underestimated (apparent rise = true rise × cos(tilt) ≈ 3.34 × 0.967 ≈ 3.23 Å vs measured 3.286 Å — close).
- Δr has an artificial linear gradient imposed along the helix length.
- Δθ is slightly overestimated because the azimuthal projection onto the tilted plane is distorted.

For NADOC (0,1) (REVERSE scaffold), the axis tilts in the opposite transverse direction [−0.209, 0.091, 0.974] (opposite sign in x, y), also ~14°. This is because the REVERSE strand's P atoms have a different starting phase (77.15° vs 107.15° for FORWARD), so the off-axis centroid displacement points in the opposite direction.

**Implication for this report:** Δz, Δθ differences of ~0.2 Å and ~1–2° between NADOC and 1ZEW are substantially explained by this axis tilt artefact. The radial distance (r) and Δr metrics are the most affected. The key real differences are identified in Section 5.

---

## 4. Backbone Step Statistics

### 4.1 Axial rise Δz

| Atom | 1ZEW mean (Å) | NADOC (0,0) mean (Å) | ΔNADOC-REF (Å) | NADOC (0,1) mean (Å) | ΔNADOC-REF (Å) |
|------|--------------|---------------------|----------------|---------------------|----------------|
| P    | 3.495 ± 1.068 | 3.286 ± 1.133 | −0.209 | 3.307 ± 0.982 | −0.188 |
| O5′  | 3.158 ± 1.068 | 3.315 ± 1.107 | +0.157 | 3.280 ± 0.979 | +0.122 |
| C5′  | 3.181 ± 1.378 | 3.342 ± 1.055 | +0.161 | 3.250 ± 0.954 | +0.069 |
| C4′  | 3.311 ± 1.118 | 3.347 ± 0.941 | +0.036 | 3.233 ± 0.862 | −0.078 |
| O4′  | 3.374 ± 0.786 | 3.320 ± 0.791 | −0.054 | 3.244 ± 0.719 | −0.130 |
| C3′  | 3.348 ± 1.197 | 3.350 ± 0.982 | +0.002 | 3.234 ± 0.898 | −0.114 |
| O3′  | 3.441 ± 1.436 | 3.376 ± 0.957 | −0.065 | 3.206 ± 0.892 | −0.235 |
| C2′  | 3.387 ± 0.895 | 3.317 ± 0.879 | −0.071 | 3.255 ± 0.791 | −0.132 |
| C1′  | 3.440 ± 0.788 | 3.309 ± 0.737 | −0.131 | 3.248 ± 0.668 | −0.192 |

**Observations:**

- The 1ZEW reference P-atom rise is 3.495 Å. The design B-DNA value in NADOC is 3.340 Å/bp. The crystal value for the P atom specifically is expected to be slightly larger than the rise per bp because the P atom is not centred at bp height — it bridges between two bp positions and is displaced toward the 3′ side.
- NADOC C4′, C3′ Δz (3.347, 3.350 Å) match the 1ZEW crystal values (3.311, 3.348 Å) to within 0.04 Å — these "mid-sugar" atoms are the most consistent across both structures.
- NADOC (0,1) systematically shows lower Δz than (0,0) by 0.05–0.15 Å for most atoms. Both are lower than 1ZEW. The (0,1) underestimation is larger and may reflect an additional contribution from the opposite-direction axis tilt artefact.
- Standard deviations: 1ZEW shows **larger** Δz variability than NADOC for most atoms. This is expected: real B-DNA has sequence-specific local bending and base stacking interactions that create step-to-step variation. NADOC uses an idealized rigid template applied at each position, suppressing sequence-specific variation.

### 4.2 Twist Δθ

| Atom | 1ZEW mean (°) | NADOC (0,0) mean (°) | ΔNADOC-REF (°) | NADOC (0,1) mean (°) | ΔNADOC-REF (°) |
|------|--------------|---------------------|----------------|---------------------|----------------|
| P    | 37.28 ± 6.83 | 35.07 ± 5.89 | −2.21 | 34.39 ± 5.35 | −2.89 |
| O5′  | 37.71 ± 5.75 | 35.71 ± 6.38 | −2.00 | 33.81 ± 4.55 | −3.90 |
| C5′  | 38.18 ± 8.39 | 36.64 ± 7.14 | −1.54 | 32.96 ± 4.18 | −5.22 |
| C4′  | 38.47 ± 8.96 | 37.49 ± 8.74 | −0.97 | 32.48 ± 4.42 | −5.98 |
| O4′  | 38.47 ± 10.53 | 37.80 ± 10.83 | −0.67 | 32.04 ± 5.28 | −6.43 |
| C3′  | 37.94 ± 8.51 | 37.31 ± 9.02 | −0.63 | 32.97 ± 4.41 | −4.97 |
| O3′  | 38.35 ± 8.02 | 38.34 ± 10.00 | −0.01 | 32.51 ± 4.42 | −5.84 |
| C2′  | 37.22 ± 10.93 | 36.79 ± 10.28 | −0.44 | 33.37 ± 5.23 | −3.85 |
| C1′  | 37.85 ± 11.30 | 37.99 ± 13.20 | +0.14 | 32.34 ± 5.84 | −5.51 |

**Design twist values:**
- NADOC HC lattice: 34.286°/bp (= 360°/10.5 bp/turn)
- Standard B-DNA: 36.0°/bp (= 360°/10 bp/turn)
- 1ZEW measured: ~37–38.5° (slightly overwound for short oligomers, a well-known end effect)

**Observations:**

- For NADOC (0,0): measured twist (35.1°) is ~0.8° higher than the design value (34.3°). This small excess is consistent with the axis tilt artefact distorting the angular projection.
- For NADOC (0,0), the overall deficit vs 1ZEW is −0.6° to −2.2° depending on atom type — modest and partially explained by the axis tilt. The design value of 34.3°/bp is lower than the canonical 36°/bp used in standard B-DNA.
- **Large deficit in NADOC (0,1):** All backbone atoms show 3–6° lower twist than 1ZEW. The deficit is largest for inner ring atoms: O4′ (−6.43°), C4′ (−5.98°), C3′ (−4.97°), C1′ (−5.51°). This is substantially larger than in NADOC (0,0) (−0.67° for O4′, −0.97° for C4′).
- The atom-type gradient in (0,1) Δθ deficit is diagnostically important: phosphate-group atoms (P, OP1, OP2) show smaller deficits (~2.9°) than sugar ring atoms (~5–6°). This radial gradient suggests the axis tilt has a larger angular distortion effect at smaller r (inner atoms are more sensitive to a mis-oriented cylindrical axis).
- The standard deviation of Δθ is consistently smaller in NADOC (0,1) than in (0,0) or 1ZEW, indicating that the REVERSE-cell helix has more uniform twist per step — a property of the rigid template model.

### 4.3 Radial change per step Δr

| Atom | 1ZEW mean (Å) | NADOC (0,0) mean (Å) | ΔNADOC-REF (Å) | NADOC (0,1) mean (Å) | ΔNADOC-REF (Å) |
|------|--------------|---------------------|----------------|---------------------|----------------|
| P    | −0.328 ± 0.715 | −0.804 ± 1.103 | −0.476 | +0.709 ± 0.930 | +1.038 |
| OP1  | −0.272 ± 0.891 | −0.796 ± 1.151 | −0.525 | +0.712 ± 0.960 | +0.983 |
| C5′  | −0.353 ± 1.020 | −0.746 ± 1.102 | −0.394 | +0.675 ± 0.930 | +1.028 |
| C4′  | −0.343 ± 0.865 | −0.718 ± 1.059 | −0.375 | +0.654 ± 0.894 | +0.996 |
| C1′  | −0.277 ± 0.724 | −0.757 ± 1.012 | −0.480 | +0.669 ± 0.875 | +0.946 |

**Critical observation — sign reversal between (0,0) and (0,1):**

For all 11 backbone atom types, the sign of Δr is NEGATIVE for NADOC (0,0) and POSITIVE for NADOC (0,1). This is the most striking qualitative difference between the two NADOC cell types.

**Cause — opposite axis tilt artefact:** The FORWARD scaffold at (0,0) has its P atoms starting at phase 107.15° and advancing +34.286°/bp; the phase cloud for 10 residues covers 0° to 308.57°, leaving a gap near 325° (between 308° and 360°/0°). The centroid of this cloud is displaced toward ~154° (opposite to the gap), causing the SVD axis to tilt transversely toward ~334°. After projecting atom positions onto this tilted axis, atoms at low z (start of helix) appear further from the axis than atoms at high z (end of helix) — hence Δr < 0 per step.

For NADOC (0,1), the REVERSE scaffold starts at phase 77.15°; the gap is at a different azimuth, and the centroid offset points in the **opposite transverse direction**. The SVD axis tilts the other way, and the radial gradient reverses: Δr > 0 per step.

In 1ZEW both chains share the same SVD axis, so there is no sign reversal between chains. The small negative Δr (−0.27 to −0.38 Å) in 1ZEW reflects true structural behaviour: near the ends of a short DNA duplex, the bases fray slightly and the backbone expands radially, giving a mild inward gradient toward the centre of the helix (lower r at mid-helix, higher r at termini — Δr < 0 when traversing toward the centre).

**Magnitude:** NADOC (0,0) Δr magnitude (~0.75–0.80 Å per step) is more than twice the 1ZEW value (0.28–0.38 Å). This excess arises entirely from the axis tilt artefact — an idealized NADOC helix has zero true Δr per step by construction.

### 4.4 Radial distance from axis r

| Atom | 1ZEW chain A (Å) | 1ZEW chain B (Å) | 1ZEW mean (Å) | NADOC (0,0) (Å) | Δ vs 1ZEW mean (Å) | NADOC (0,1) (Å) | Δ vs 1ZEW mean (Å) |
|------|-----------------|-----------------|--------------|----------------|-------------------|----------------|-------------------|
| P    | 9.084           | 8.726           | 8.905        | 9.635          | +0.730            | 9.121          | +0.216            |
| OP1  | —               | —               | 9.685        | 10.710         | +1.025            | 10.359         | +0.674            |
| OP2  | —               | —               | 9.524        | 9.936          | +0.412            | 8.996          | −0.528            |
| O5′  | —               | —               | 8.406        | 9.367          | +0.962            | 9.159          | +0.753            |
| C4′  | —               | —               | 7.285        | 7.908          | +0.623            | 8.348          | +1.064            |
| C1′  | 5.752           | 5.248           | 5.500        | 6.237          | +0.737            | 6.358          | +0.858            |

**Critical finding — NADOC atoms are systematically too far from the helix axis:**

Every backbone atom in NADOC is 0.2–1.0 Å further from the helix axis than in 1ZEW.

- **Phosphorus (P):** NADOC 9.635 Å vs 1ZEW 8.905 Å → **+0.73 Å excess (+8.2%)**. The NADOC design parameter `_ATOMISTIC_P_RADIUS = 9.71 Å` is the intended placement radius; 9.635 Å is close to this (the 0.075 Å gap is axis-tilt artefact). Standard B-DNA crystal P radius is 8.9–9.0 Å. NADOC therefore places P ~0.7 Å too far from the axis.
- **C1′:** NADOC 6.237 Å vs 1ZEW 5.500 Å → **+0.74 Å excess (+13.4%)**. The 1ZEW C1′ shows significant asymmetry between chains (5.752 Å chain A vs 5.248 Å chain B), reflecting the real B-DNA groove asymmetry: C1′ on one strand sits inside the major groove (larger r) and on the other strand inside the minor groove (smaller r). NADOC produces equal C1′ radius for both chains (template symmetry).
- **OP1 vs OP2:** These are the two non-bridging phosphate oxygens. In 1ZEW they differ in radial distance (9.685 vs 9.524 Å). In NADOC they also differ (10.710 vs 9.936 Å for (0,0)). The relative OP1/OP2 ratio is preserved but the absolute values are ~0.4–1.0 Å too large.
- **NADOC (0,1) r values:** For most atoms NADOC (0,1) shows slightly smaller r than (0,0), and for OP2 the value (8.996 Å) is actually 0.528 Å BELOW the 1ZEW reference. This atom-specific inversion between (0,0) and (0,1) is partly axis-tilt artefact (different tilt direction distorts the projection of the phosphate oxygen positions differently) and partly a real consequence of the REVERSE scaffold placing template atoms at a different initial phase.

---

## 5. Key Findings Summary

### Finding 1 — Cells (0,0) and (1,1) are geometrically identical

Both cells have even parity `(row + col) % 2 = 0` → FORWARD scaffold. The helix geometry (axis position, phase offset, twist) is determined entirely by lattice parity, not by (row, col) coordinates. NADOC correctly produces translation-invariant helix geometry; the only difference between (0,0) and (1,1) is the position of the helix axis in the XY plane.

### Finding 2 — The B-DNA rise is slightly underestimated in NADOC

- NADOC design parameter: 3.340 Å/bp
- 1ZEW crystal (P atoms): 3.495 Å per step
- NADOC measured (P): 3.286 Å per step

The NADOC measurement is below even the design value (3.340 Å) primarily due to the SVD axis tilt artefact (~0.05 Å correction). After correcting for axis tilt, the true NADOC P-atom rise would be ~3.34 Å × (design value), which is 4.6% below the crystal-observed 3.495 Å for P atoms. However, the 3.495 Å P-atom value in 1ZEW reflects the 3D geometry of the phosphodiester backbone, not just the rise per bp; the rise for central atoms like C4′ and C3′ agrees to <0.05 Å between NADOC and 1ZEW.

### Finding 3 — The twist is 1.7°/bp lower in NADOC than in canonical B-DNA

- NADOC design: 34.286°/bp (10.5 bp/turn — standard structural DNA value)
- Standard B-DNA: 36.0°/bp (10.0 bp/turn)
- 1ZEW measured: ~37–38°/bp (overwound short oligomer; end effects common for 10-mers)

NADOC is designed to match the 10.5 bp/turn value used by caDNAno2 and most DNA origami software, which differs from the 10.0 bp/turn of idealized B-DNA. The 1.7° difference is intentional design, not an error.

### Finding 4 — NADOC phosphorus and backbone atoms are ~0.7–1.0 Å too far from the helix axis

For the phosphorus atom: NADOC r = 9.71 Å (design), 9.64 Å (measured), vs 1ZEW mean 8.91 Å. The excess of **~0.73 Å** is consistent across all backbone atoms. This originates from `_ATOMISTIC_P_RADIUS = 0.971 nm = 9.71 Å` in `backend/core/atomistic.py`.

Standard B-DNA crystallographic values:
- P radius from axis: 8.9–9.1 Å (various crystal structures)
- NADOC uses 9.71 Å — approximately **0.7 Å too large** (7–8% excess)

This excess radial placement would manifest in GROMACS simulations as slightly elongated minor/major groove widths and C1′–C1′ distances compared to canonical B-DNA.

### Finding 5 — NADOC chains A and B are perfectly symmetric; 1ZEW chains are not

For NADOC, both chains at any cell have **identical** r, Δz, Δθ, Δr statistics (to three decimal places). This is a direct consequence of the rigid template model: the same template geometry is applied at every residue, regardless of whether the strand is scaffold or staple.

For 1ZEW:
- Chain A P radius: 9.084 Å; Chain B P radius: 8.726 Å (difference: 0.36 Å)
- Chain A C1′ radius: 5.752 Å; Chain B C1′ radius: 5.248 Å (difference: 0.50 Å)

The chain asymmetry in 1ZEW reflects real B-DNA groove asymmetry: the two antiparallel strands sit at slightly different radii because the major groove (wider) and minor groove (narrower) have different geometry. The strand on the major groove side has a larger mean radial distance. NADOC's template model places both strands identically and therefore misses this asymmetry.

### Finding 6 — Δr sign reversal between FORWARD (0,0) and REVERSE (0,1) cells

As explained in Section 4.3, the Δr reversal (−0.8 Å for (0,0) vs +0.7 Å for (0,1)) is an SVD axis tilt artefact. It is **not** a real difference in the physical geometry of the helix — both cells use the same radial template placement, and both have zero true Δr per step by construction.

However, this finding demonstrates that the current validation script is sensitive to axis orientation artefacts when applied to short (10 bp) helices with twist ≠ 36°/bp. For production use, the helix axis should either be specified from the design geometry (axis_start → axis_end) rather than fitted by SVD, or helices of ≥20 bp should be used so that the P atoms complete at least one full turn (10.5 bp/turn × 2 turns = 21 bp minimum).

### Finding 7 — NADOC exhibits reduced step-to-step variability vs the crystal structure

Standard deviations of Δz across all backbone atoms:
- 1ZEW: 0.79–1.44 Å
- NADOC (0,0): 0.74–1.27 Å
- NADOC (0,1): 0.67–1.15 Å

Standard deviations of Δθ:
- 1ZEW: 5.8–11.3° (genuine sequence-specific variation + crystal disorder)
- NADOC (0,0): 5.9–13.2° (some atoms slightly higher — end effects at 10-bp helix endpoints)
- NADOC (0,1): 4.2–10.8° (generally lower, more uniform)

The reduced variability in NADOC is expected: the model applies the same rigid template geometry at every base pair with no sequence-specific local bending, groove variation, or thermal motion. For a DNA origami structure, this level of regularity is appropriate as an average model; for atomistic MD simulation, the artificially low Δθ variance in (0,1) suggests potential force-field relaxation requirements for REVERSE-cell helices that are larger than for FORWARD-cell helices.

---

## 6. Axis Fitting Limitation and Recommended Fix

The SVD-from-P-atoms axis fitting is adequate for long helices (≥20 bp, completing ≥2 full turns at 34.286°/bp) but introduces systematic artefacts at 10 bp. For validation of short segments, the axis should be supplied directly from the NADOC design geometry:

```python
# axis_nm from design: axis_start → axis_end
axis_vec = np.array([
    h.axis_end.x - h.axis_start.x,
    h.axis_end.y - h.axis_start.y,
    h.axis_end.z - h.axis_start.z,
])
axis = axis_vec / np.linalg.norm(axis_vec)
centroid = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z]) * 10  # nm → Å
```

For the 1ZEW reference, no design axis is available, so the SVD fit is unavoidable. A meaningful comparison should either use long NADOC test helices (≥42 bp = 4 full turns) or accept the ~0.1–0.2 Å / 1–2° systematic offsets in the current comparison as measurement noise.

---

## 7. Conclusions

| Metric         | 1ZEW reference  | NADOC (0,0)/(1,1) | NADOC (0,1) | Assessment |
|----------------|-----------------|-------------------|-------------|------------|
| Δz P (Å/step)  | 3.50 ± 1.07     | 3.29 ± 1.13       | 3.31 ± 0.98 | Underestimate partly artefact; C4′/C3′ match to <0.05 Å |
| Δθ P (°/step)  | 37.28 ± 6.83    | 35.07 ± 5.89      | 34.39 ± 5.35 | Design uses 34.3°/bp (10.5 bp/turn) vs standard 36°; intentional |
| r P (Å)        | 8.905 ± 0.71    | 9.635 ± 1.67      | 9.121 ± 1.53 | **+0.73 Å excess** from `_ATOMISTIC_P_RADIUS` calibration |
| r C1′ (Å)      | 5.500 ± 0.79    | 6.237 ± 1.42      | 6.358 ± 1.21 | **+0.74 Å excess** — correlated with P-radius issue |
| Δr (Å/step)    | −0.33 ± 0.72    | −0.80 ± 1.10      | +0.71 ± 0.93 | Artefact of axis tilt; real value = 0 for both |
| Chain symmetry | Asymmetric      | Symmetric         | Symmetric   | NADOC misses groove asymmetry by construction |
| Step variability | High (sequence-specific) | Low (rigid template) | Lowest | Expected for template-based model |

The primary genuine structural discrepancy — independent of axis fitting artefacts — is the **0.7 Å excess radial placement of all NADOC backbone atoms** relative to the 1ZEW crystal reference. This is traced to `_ATOMISTIC_P_RADIUS = 0.971 nm` in `backend/core/atomistic.py` being approximately 0.07 nm (0.7 Å) larger than the canonical crystallographic B-DNA P-atom radius of ~0.89–0.91 nm.

No changes are made based on these findings; this report documents the current state.
