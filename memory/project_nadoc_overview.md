---
name: NADOC project overview
description: What NADOC is, its architecture, and the simulation pipeline it exports
type: project
originSessionId: 850be451-9e2e-4b70-a3e8-bb898f34b034
---
NADOC is a DNA origami design tool (web app + Python backend) that builds helical bundles with honeycomb lattice geometry. It supports the Dietz loop/skip mechanism for global bending.

**Why:** Understanding the broader context helps interpret feature requests and simulation bugs.

**How to apply:** Frame all backend work in terms of the design → atomistic model → GROMACS export pipeline.

Key layers:
- `backend/core/models.py` — Pydantic models: Design, Strand, Domain, Helix, LoopSkip, OverhangSpec
- `backend/core/atomistic.py` — builds an all-atom PDB from the design; handles skip-site backbone geometry via `_minimize_backbone_bridge`
- `backend/core/gromacs_package.py` — builds the full GROMACS simulation package (conf.gro, topol.top, em.mdp, nvt.mdp, run scripts)
- `backend/core/sequences.py` — scaffold/staple sequence assignment with loop/skip awareness

Export modes:
- **Deformed**: helices bent to their designed shape (uses oxDNA-derived coordinates)
- **Non-deformed (original positions)**: helices are straight; skip/loop sites create backbone strain that must be handled carefully in the simulation setup
