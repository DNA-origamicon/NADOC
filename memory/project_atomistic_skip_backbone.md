---
name: Atomistic skip-site backbone bridge minimization
description: How atomistic.py handles the O3'→P gap at skip sites
type: project
originSessionId: 850be451-9e2e-4b70-a3e8-bb898f34b034
---
Skip sites (LoopSkip delta=-1) omit a nucleotide, creating an O3'(N-1)→P(N+1) backbone bond that spans ~5-8 Å instead of the canonical 1.6 Å.

**`_minimize_backbone_bridge`** in `backend/core/atomistic.py` (~line 1123-1202):
- scipy L-BFGS-B optimizer
- Moves O3'(src), P(dst), O5'(dst) to minimize deviation from canonical bond lengths and angles
- Called from the backbone bridge building code (~line 895-955) when a skip site is encountered

**Residual problem:** Even after `_minimize_backbone_bridge`, the adjusted atoms create strain in the surrounding residues. This strain propagates into aromatic C2-H2 bonds of adjacent adenine residues during unconstrained EM (see skip-site GROMACS fix memory).

**How to apply:** When debugging geometry issues near skip sites, check both the output of `_minimize_backbone_bridge` AND the EM output GRO (em.gro). conf.gro may look fine (~1.0 Å C2-H2) while em.gro has diverged to 2.5 Å.
