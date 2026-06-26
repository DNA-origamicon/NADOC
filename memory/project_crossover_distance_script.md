---
name: Crossover arc distance script — key geometry validation tool
description: scripts/measure_crossover_distances.py validates importer geometry by measuring backbone distances at all lattice-neighbor crossover sites
type: project
originSessionId: b8a5dca6-8e5d-4d81-b1a6-8bc73570a376
---
`scripts/measure_crossover_distances.py` is the primary tool for validating that importers (cadnano, scadnano) produce correct helix axis positions and phase offsets.

**What it measures:** For every pair of lattice-adjacent helices (staple and scaffold crossover offset tables), measures the 3D backbone bead distance between the two beads that would be connected at each crossover site. Non-neighbor (forced) crossovers are excluded by construction — the offset tables only encode direct lattice adjacencies.

**Expected bounds:** All crossover backbone distances should be ≤ 1.2 nm for a correctly imported design. Values above this indicate axis position or phase errors in the importer.

**Crossover type labels:** pN (row−1), pE (col+1), pS (row+1), pW (col−1) — reported for every site.

**File format auto-detection:** .nadoc (native), .json (cadnano v2), .sc (scadnano).

**Key flags:**
- `--threshold 1.2` — lists all sites above threshold, sorted worst-first
- `--staple-only` / `--scaffold-only`
- `--xtype pN pS` — filter to specific neighbor directions
- `--hist` — ASCII histogram
- `--verbose` — every site

**Known baseline (2x4hb SQ test, cadnano, 2026-04-20):** Staple: 0/80 failures ✓. Scaffold: 160/240 failures — open issue, separate from staple geometry. Do NOT attempt to fix scaffold failures by changing phase constants (see feedback_phase_constants_locked.md).

**Why:** crossover arc distances above ~1.2nm are a real problem visible to users as arcs that don't look like they connect cleanly. The script makes importer geometry errors immediately quantifiable.
