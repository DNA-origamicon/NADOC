---
name: REFERENCE_ATOMISTIC
description: Phase AA atomistic view — 1BNA NERF template, CPD motivation, PDB/PSF export, frame constants
type: project
---

## Current Atomistic Template (locked 2026-03-25)

Module: `backend/core/atomistic.py`

### Sugar Template (`_SUGAR`)
- Ring atoms (C4'–C1') from 1BNA crystallographic data, shifted +0.1689 nm in z for base coplanarity
- C5'/O5'/P via NERF from 1BNA internal coords, then adjusted with δ=+88°, γ=−77°, β=+180° torsions
- OP1/OP2: 2D grid search minimizing variance of 6 pairwise O-O distances (all four O-P-O = 109.43°)

### Frame Constants
```python
_FRAME_ROT_RAD  = 39° (0.6806... rad)
_FRAME_SHIFT_N  = −0.07 nm
_FRAME_SHIFT_Y  = −0.59 nm
_FRAME_SHIFT_Z  = 0
```
These are exposed as query params on `GET /design/atomistic` for override.

### Domain Transition Bond Generation
Inter-residue O3'→P bonds span helix boundaries via domain traversal (`prev_o3_serial` not reset at domain transitions). This enables correct PDB connectivity across domain boundaries.

## API
- `GET /design/atomistic` — returns all-atom coordinates
  - Query params: `frame_rot_rad`, `shift_n`, `shift_y`, `shift_z` (override frame constants)
- `GET /design/export/pdb` — PDB file (coarse-grained backbone)
- `GET /design/export/psf` — PSF topology for NAMD
- `GET /design/export/namd-complete` — full NAMD simulation bundle (.zip)

## Display
- `frontend/src/scene/atomistic_renderer.js` — VdW spheres or ball-and-stick
- `store.atomisticMode`: `'off' | 'vdw' | 'ballstick'`
- Arcs hidden when atomistic active: `unfoldView.setArcsVisible(false)`

## CPD Motivation (Primary Purpose of Phase AA)

The atomistic layer was built primarily to study the effects of **CPD (cyclobutane pyrimidine dimer) photocrosslinking** on DNA origami structure/dynamics in NAMD simulations.

CPD forms when UV light creates covalent C5–C5 and C6–C6 bonds between adjacent thymine bases on the same strand. Conventional tools cannot handle this modification. NADOC's atomistic layer is designed to eventually support:
1. Modified DT residue template (cyclobutane ring geometry)
2. Inter-residue LINK records in PDB (C5–C5, C6–C6 bonds)
3. PSF patches for CPD with CHARMM36 parameters

Reference implementation: `/home/joshua/scadnano_cpd/` — scadnano_cpd already implements CPD PDB export with LINK records and photoproduct junctions.

## Design for Extensibility
All atomistic architecture decisions assume non-canonical residues are possible:
- Generic template parser (add CPD templates later)
- Explicit inter-residue bond model (not just O3'→P)
- PDB LINK records for ALL inter-residue covalent bonds
- PSF supports non-standard residue patches (CHARMM36 stream files)

## NAMD Package Details
- ZIP: `{name}.pdb`, `{name}.psf` (complete w/ angles+dihedrals), `namd.conf`, `forcefield/`, `scripts/monitor.py`, `launch.sh`, `README.txt`
- GBIS implicit solvent; 2000-step minimize + 50000-step NVT at 310 K
- PSF: dynamic `!NTITLE` count, CHARMM36 atom types for all 4 DNA bases
- `launch.sh`: tries namd3→namd2→apt install; auto-detects CPU count; GPU detection
