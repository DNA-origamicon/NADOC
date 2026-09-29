# 3x6SQ_norm_skips Alpine production: periodic-image interference

Analyzed local production job `9b1151dfca21`, parent relaxation `50bd30b7e7ad`. The downloaded DCD contains 678 frames at 0.1 ns spacing, covering 0.1–67.8 ns, not the requested full 200 ns. Job metadata says user-stopped and download verified; stale SLURM/segment fields are inconsistent, so duration here comes from the DCD and timestep.

## Findings

The DNA directly contacts periodic copies on both transverse axes and the longitudinal axis. This simulation cannot be interpreted as the deformation of an isolated bundle. Periodic-image interactions are a plausible contributor to the observed corrugation/local bending, but these coordinates alone do not establish compressive stress or prove the cause of buckling.

| Measurement | 0.1 ns | 67.8 ns |
|---|---:|---:|
| Periodic cell (nm) | 15.369 × 8.783 × 74.806 | 15.376 × 8.787 × 74.840 |
| Closest DNA heavy-atom distance to a periodic copy | 0.960 nm | 0.257 nm |
| Interior centerline chord | 66.400 nm | 68.590 nm |
| Interior centerline contour | 66.928 nm | 69.736 nm |
| Maximum centerline displacement from its end chord | 0.417 nm | 1.625 nm |

Every sampled frame has a DNA-image separation below the configured 1.0 nm short-range cutoff. Separation reaches 0.300 nm at 3.1 ns. The smallest sampled value is 0.246 nm. In the final frame, nearest separations are 0.283 nm across x, 0.257 nm across y, and 0.262 nm end-to-end across z. For the positive-axis image queries, respectively 1481, 2108, and 327 source heavy atoms have an image neighbor within 1 nm (these are per-image counts, not unique atom-pair counts). Additional diagonal image contacts occur.

The chord length grows about 3.3%, so the evidence does not support net axial shortening during production. Bending grows, and the cross-section/ends spread into the periodic neighbors. A nearly unchanged box volume also rules out substantial ongoing global barostat shrinkage as the observed production-time change; local stress remains unmeasured.

## Setup evidence

The parent `nadoc_md_run.json` records a fallback from rotation-safe sizing to `bbox`: the proposed rotation-safe cell was estimated at ~46.7 million atoms against a 2.11 million atom cap. Padding was reduced from 2.0 to 1.2 nm. Its own recorded note warns that free dynamics in the fallback box is not trustworthy. Production has `allow_undersized_cell: true`, `orientation_restraint: false`, `enm_restraints: off`; the actual NAMD config has `constraints off`, PME enabled, 10 Å cutoff and an isotropic NPT piston. The remaining extra bonds concern hydrated magnesium.

## Interpretation and next experiment

Treat this trajectory as contaminated by direct periodic self-contact. A larger, freshly solvated box with adequate clearance throughout the trajectory is needed before attributing the waviness to the design's intrinsic mechanics. Start from a pre-contact or independently relaxed configuration rather than assuming the current shape is unbiased. If using an elongated box with an orientation restraint for feasibility, recognize that it changes rotational sampling and verify actual image distances; orientation control alone will not repair insufficient clearance for internal deformation. A comparison in a sufficiently spacious box is needed to test causality. No simulations or application settings were changed.

## Reproducibility and limits

`analyze.py` samples every tenth saved frame (1 ns) plus the last, 69 frames total. It reads unwrapped coordinates (`wrapAll off`), selects 149666 DNA heavy atoms, and computes exact nearest-neighbor distances against the 26 adjacent orthorhombic cell translations (13 unique directions by symmetry), using each DCD frame's own cell. Bounding-box lower bounds prune irrelevant translations. Values between sampled frames are not characterized.

Centerlines use the mean of C1' positions in 32 fixed initial-z bins, trimming 2.5 nm from each initial end. Their chord/contour lengths therefore describe an interior centerline, not total molecular extent or per-duplex strain. Bin-scale turn angles are sensitive to staggered ends, routing, and the coarse center definition and should not be interpreted as proof of mechanical buckling. No force decomposition, stress calculation, or larger-box control was performed. The reference-relative WC contact metric in the raw JSON is a plan-based diagnostic, not a validated count of intact base pairs for this analysis, and is not used for the conclusions.

Artifacts: `metrics.json`, `contacts.json`, `profiles.npz`, `diagnostics.png`, `contacts.png`, and the two scripts.

NAMD reference: https://www.ks.uiuc.edu/Research/namd/3.0.2/ug/node25.html (cutoff and periodic electrostatics). PME also includes long-range interactions; absence of a short-range contact alone would not establish box-size convergence.
