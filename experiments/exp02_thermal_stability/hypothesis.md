# Exp02 — Thermal Stability Hypothesis

## System
42 bp single duplex, bond_stiffness=1.0, bend_stiffness=0.3, bp_stiffness=0.5.
Run 500 frames (n_substeps=20 each).

## Three noise conditions
| Label | noise_amplitude (nm/substep) |
|-------|------------------------------|
| Low   | 0.01                        |
| Mid   | 0.05                        |
| High  | 0.10                        |

## Hypothesis
- **Low (0.01)**: RMSD from initial positions stays bounded below ~0.3 nm.
  Helix visually stable; thermal fluctuations are sub-angstrom per nucleotide.
- **Mid (0.05)**: Visible thermal motion (~0.5–2.0 nm RMSD) but double-helix
  remains structurally intact. Backbone bond mean stays within ~0.05 nm of rest.
- **High (0.10)**: Significant RMSD growth (>2 nm), possibly unbounded or showing
  helix disorder. Backbone bond lengths may deviate noticeably from rest.

## Key questions
1. At what noise amplitude does RMSD grow without bound vs. reach a plateau?
2. Is bond length mean stable under thermal noise (indicates constraint solver
   keeps up with thermal kicks)?
3. What noise amplitude corresponds to "physiologically relevant" thermal motion
   and what is the appropriate slider range for the UI?
