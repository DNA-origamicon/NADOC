---
type: project
status: blocked
authority: canonical
review_after: 2026-10-01
---
# Periodic MD

Canonical guide for explicit-solvent axial-periodic DNA-origami simulation. Detailed experiments,
literature notes, and retired run status are in [the archive](project_periodic_md_archive.md).

## Current state

- `backend/core/periodic_cell.py` slices a design, builds the atomistic cell, creates wrap bonds,
  solvates, places ions, and emits a NAMD package.
- `backend/core/namd_solvate.py` owns periodic GROMACS solvation and NAMD configuration rendering.
- The old standalone frontend periodic-MD preview was removed; any replacement belongs inside the
  unified Simulate section.
- Honeycomb repeat is 21 bp; one repeat is `21 * BDNA_RISE_PER_BP = 7.014 nm`.
- Wrapped O3′–P geometry uses a periodic-image construction and NAMD uses `wrapNearest on`.

## Binding decisions

- The periodic production cell is prepared once and inherited. Do not let pressure coupling change
  the axial repeat and compress helical rise.
- Consensus sequence votes across full-design periods; reverse bases are Watson–Crick complements
  of the forward consensus.
- The canonical Aksimentiev-style CHARMM36 origami protocol uses a permanent elastic network.
  “Unrestrained” production without that network is not equivalent and may require an AMBER DNA
  force field instead.
- Periodic MD is governed by [architecture decisions](architecture_decisions.md).

## Blocker and open decisions

Generated configuration, historical experiment files, and old summaries disagree about whether
XY or Z was pressure-coupled. User intent is to equilibrate pressure and then lock the production
axial length, but the exact production protocol has not been normalized across generator, artifact,
and documentation. Resolve that protocol before interpreting or launching new periodic production.

Also re-evaluate the historical Mg(H₂O)₆ extra-bond force constant and the very short historical
equilibration ladder against the canonical protocol before reusing those experiments.

## Verification

Use unit tests for slicing, wrap bonds, cell dimensions, and rendered configuration. Real periodic
NAMD runs are heavy and require a user-opened test session or explicitly authorized experiment.
