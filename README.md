# NADOC — Not Another DNA Origami CAD

A research-grade DNA origami design tool built for precision, extensibility, and
scientific rigour.  Every design decision is grounded in peer-reviewed literature
and validated through a systematic experiment pipeline.

## Architecture

NADOC enforces a strict three-layer separation:

| Layer | Purpose | Files |
|-------|---------|-------|
| **Topological** | Strand graph, crossover connectivity, loop/skip modifications. Ground truth. | `backend/core/models.py`, `lattice.py`, `loop_skip_calculator.py` |
| **Geometric** | Helix axes, nucleotide positions derived from topology + B-DNA constants. | `backend/core/geometry.py`, `deformation.py` |
| **Physical** | XPBD/oxDNA relaxed positions. Display only, never written back. | `backend/physics/xpbd.py`, `oxdna_interface.py` |

## Stack

- **Backend**: Python 3.12, FastAPI, Pydantic v2, NumPy, uv
- **Frontend**: Three.js (Vite), vanilla ES modules
- **2D Editor**: Canvas 2D (pathview) + SVG (sliceview), BroadcastChannel sync

## Feature Status

| Phase | Feature | Status | Tests |
|-------|---------|--------|-------|
| 0 | Foundation (models, geometry, validator) | ✅ Complete | 29/29 |
| 1 | Geometry visualisation harness | ✅ Complete | 35/35 |
| 2 | Bundle creator (honeycomb cross-section, extrude) | ✅ Complete | 99/99 |
| 3 | Slice plane editor (3D layer addition) | ✅ Complete | 111/111 |
| 4 | Staple crossover editor (half-crossover, DX motifs, autostaple) | ✅ Complete | 164/164 |
| 5 | Physics layer (XPBD real-time + oxDNA batch) | ✅ Complete | 192/192 |
| 6 | Geometric bend/twist (deformation layer, cluster system, animation) | ✅ Complete | 192/192 |
| 7 | Topological loop/skip (Dietz mechanism, limits, experiments) | ✅ Complete | 437/437 |
| S | Sequences, M13mp18 scaffold, CSV export | ✅ Complete | — |
| SQ | Square lattice support (33.75°/bp, 4 neighbors) | ✅ Complete | 23 |
| CN | caDNAno v2 import/export | ✅ Complete | 23 |
| AA | Atomistic 3D view, PDB/PSF export, NAMD package | ✅ Complete | — |
| FEM | Euler-Bernoulli FEM, RMSF heatmap, WebSocket streaming | ✅ Complete | 275 |
| UX | Selection filter, draggable ends, overhang 3D, lasso | ✅ Complete | — |
| SC | scadnano import (HC + SQ grids, loopouts, extensions) | ✅ Complete | 11 |
| **Editor** | **Interactive 2D cadnano editor (Phase 1)** | ✅ **Complete** | **17** |
| 8 | Parts library + assembly CAD | 🔵 Planned | — |
| 9 | Checker integrations (oxDNA, CanDo, SNUPI) | 🔵 Planned | — |

**Total: 559 tests passing**

## 2D Cadnano Editor

A full interactive caDNAno-style 2D editor running in a separate browser tab,
synced bidirectionally with the 3D view via BroadcastChannel and a shared FastAPI
backend.

### Sliceview (SVG)
- Honeycomb and square lattice grids
- Click cell to activate/deactivate helices (calls backend API)
- Helix labels reflect creation order

### Pathview (Canvas 2D)
- Activated helices as horizontal double tracks (forward + reverse)
- Scaffold pencil tool: click-drag to draw scaffold domains cell by cell
- Auto-scaffold button routes and connects painted segments
- Zoom, pan, helix label gutter

### Sync model
```
2D mutation → POST API → BroadcastChannel "design-changed" → 3D re-fetches
3D mutation → BroadcastChannel "design-changed" → 2D re-fetches and redraws
```

Multiple 2D editor tabs stay in sync automatically — backend is ground truth.

## Additional Features

### Cluster system & animation (Phase 6)
Helices grouped into named clusters; per-cluster deformation ops; feature log
timeline with draggable playhead; pre-baked animation at 60 fps (one geometry
batch fetch, then pure client-side lerp).

### Loop/skip topological deformation (Phase 7)
Implements the Dietz, Douglas & Shih (Science 2009) mechanism for bending and
twisting bundles by inserting/deleting base pairs. Enforces physical limits
(6–15 bp/turn twist density, min bend radius).

### Atomistic & NAMD export
All-atom template with PDB/PSF export. One-click NAMD simulation package (ZIP)
with GBIS implicit solvent config.

### FEM structural analysis
Euler-Bernoulli beam model; RMSF heatmap via eigenvalue decomposition; real-time
WebSocket streaming.

### Fluorescence & FRET
Strand terminal extensions with fluorophore beads; FRET checker with Förster
radii (Cy3→Cy5, FAM→TAMRA, ATTO488→ATTO550).

### Surface representations
Van der Waals and solvent-excluded surfaces via marching cubes; strand coloring;
opacity slider.

## Development

```bash
# Start backend + frontend dev servers
just dev

# Run all tests
just test

# Run a specific test file
just test-file tests/test_loop_skip.py

# Format and lint
just fmt
just lint

# Run an experiment
uv run python experiments/exp10_twist_loop_skip/run.py
```

## Experiment pipeline

Each experiment in `experiments/expNN_*/` follows a fixed structure:

```
hypothesis.md   — prediction written before running
run.py          — executable script producing results/ artefacts
conclusion.md   — analysis written after running
results/        — figures (*.png) and metrics (metrics.json)
```

## Literature

Key references in `Literature/`:

- **Dietz, Douglas & Shih, Science 2009** — Loop/skip bend/twist mechanism
- **Douglas et al., Nature 2009** — caDNAno tool (crossover conventions)
- **Schlick et al. 2022** — scadnano conventions
- **Rothemund, Nature 2006** — Scaffolded DNA origami primer
