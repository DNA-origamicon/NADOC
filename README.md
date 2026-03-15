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
- **Database**: SQLite / SQLModel (Phase 8+)

## Feature Status

| Phase | Feature | Status | Tests |
|-------|---------|--------|-------|
| 0 | Foundation (models, geometry, validator) | ✅ Complete | 29/29 |
| 1 | Geometry visualisation harness | ✅ Complete | 35/35 |
| 2 | Bundle creator (honeycomb cross-section, extrude) | ✅ Complete | 99/99 |
| 3 | Slice plane editor (3D layer addition) | ✅ Complete | 111/111 |
| 4 | Staple crossover editor (half-crossover, DX motifs, autostaple) | ✅ Complete | 164/164 |
| 5 | Physics layer (XPBD real-time + oxDNA batch) | ✅ Complete | 192/192 |
| 6 | Geometric bend/twist (deformation layer, UI scaffolding) | ✅ Complete | 192/192 |
| 7 | **Topological loop/skip (Dietz mechanism, limits, experiments)** | ✅ Complete | **238/238** |
| 8 | Parts library + assembly CAD | 🔵 Planned | — |
| 9 | Checker integrations (oxDNA, CanDo, SNUPI) | 🔵 Planned | — |

## Phase 7 — Loop/Skip Topological Deformation

Phase 7 implements the physical mechanism from **Dietz, Douglas & Shih (Science
2009)** for bending and twisting DNA origami bundles by inserting and deleting
base pairs in specific array cells.

### Key concepts

- **Array cell**: a 7-bp segment between consecutive crossover planes (= 240° twist)
- **Skip (δ = −1)**: removes a base pair → local overtwist → left-handed torque + pull
- **Loop (δ = +1)**: adds a base pair → local undertwist → right-handed torque + push

**Pure twist**: uniform skips/loops across all helices → global twist, bends cancel.
**Pure bend**: gradient of skips (inner) + loops (outer) across the cross-section → global bend, twists cancel.

### Physical limits (enforced by the calculator)

| Constraint | Value | Source |
|-----------|-------|--------|
| Min twist density | 6 bp/turn | Dietz et al. — below this, folding quality degrades |
| Max twist density | 15 bp/turn | Dietz et al. — above this, defect frequency rises sharply |
| Max δ per cell | ±3 bp | Derived from above limits at 10.5 bp/turn baseline |
| Min bend radius | 7 × r_max / 3 nm | Geometric formula; ≈ 5.25 nm for 3-row bundle |

### Experimental validation (see `experiments/`)

| Experiment | Finding |
|-----------|---------|
| **exp10** — Twist calibration | R² = 0.9999; max rounding residual = 16.8°; Dietz 10/11 bp/turn calibration reproduced exactly |
| **exp11** — Bend radius calibration | Mean relative error 3.5%; R_min = 5.25 nm (paper: ~6 nm); limits correctly enforced |

### API endpoints (Phase 7)

```
POST /api/design/loop-skip/twist   — Apply uniform skips/loops for global twist
POST /api/design/loop-skip/bend    — Apply gradient skips/loops for global bend
GET  /api/design/loop-skip/limits  — Query min radius and max twist for a segment
DELETE /api/design/loop-skip       — Remove modifications from a bp range
```

## Development

```bash
# Start backend + frontend dev servers
just dev

# Run all tests
just test

# Run a specific test file
just test-file tests/test_loop_skip.py

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

Experiments validate specific quantitative properties of the calculator and
physics engine, with explicit pass/fail thresholds stated in the hypothesis.

## Literature

Key references in `Literature/`:

- **Dietz, Douglas & Shih, Science 2009** — Loop/skip bend/twist mechanism (Phase 7)
- **Douglas et al., Nature 2009** — caDNAno tool (Phase 2–4 crossover conventions)
- **Schlickt et al. 2022** — scadnano conventions
- **Rothemund, Nature 2006** — Scaffolded DNA origami primer
