# Handoff prompt — auto_scaffold fails to route a single scaffold on asymmetric cross-sections

Copy the block below into a fresh session.

---

Investigate why `auto_scaffold` fails to produce a **single connected scaffold** on asymmetric
square-lattice cross-sections, leaving disjoint per-helix scaffolds.

## What I observed (reproducible, headless)
Building square-lattice bundles headlessly and counting `[s for s in design.strands if s.is_scaffold]`:

| cross-section (cells)                     | helices | scaffolds | verdict |
|---|--:|--:|---|
| solid 2×3 / 4×4 / 3×6, hollow tubes d3–d6 | 4–20 | **1** | OK |
| solid **3×3**                             | 9  | **2** | BROKEN |
| **L** (col 0 + bottom row of a 4×4)       | 7  | **2** | BROKEN |
| **triangle** (staircase, col ≤ row, 4 rows)| 10 | **10** | TOTAL FAILURE (every helix its own scaffold) |
| **notch** (solid 4×4 minus top-right 2×2) | 12 | **1** | OK |

So it is not strictly "asymmetric" — some asymmetric shapes route (notch), some symmetric ones don't
(3×3). It correlates with whether the seamed router can find a single Hamiltonian-ish path through the
cell adjacency graph. Thin/odd shapes (triangle staircase, L) defeat it.

## Minimal repro
```python
from backend.api import headless_build as hb
from backend.api import state as ds
from backend.core.models import LatticeType
SQ = LatticeType.SQUARE
triangle = [(r, c) for r in range(4) for c in range(r + 1)]   # 10 cells
with hb.scratch_session(SQ):
    hb.create_bundle(triangle, 160, lattice=SQ, name="tri")
    hb.auto_scaffold(seamless=False)   # <-- routes 10 disjoint scaffolds
    hb.auto_crossover(); hb.auto_break()
    d = ds.get_or_404()
print(sum(s.is_scaffold for s in d.strands), "scaffolds for", len(d.helices), "helices")
```
Audit helper (single scaffold + adjacency-only crossovers + full duplex mesh) lives in
`experiments/exp39_hollow_tube_authority/sweep.py::audit` and `experiments/exp40_asymmetric_coupling/g3.py::audit`.

## Why it matters
It blocks the CanDo-autorefine generalization (G3, asymmetric-section validation — see
`experiments/exp37_cando_skip_twist_map/GENERALIZATION.md` and `memory/project_cando_fem.md`): the FEM
reads duplex coverage from strand topology, so a disjoint scaffold gives garbage authority numbers.
More broadly, any asymmetric origami the user draws may fail to auto-route.

## Where to look
- Entry: `backend/api/headless_build.py::auto_scaffold` → `_route_auto_scaffold_seamed`
  (seamed = Hamiltonian path + Holliday seam) / `_route_auto_scaffold_seamless`.
- Routers: `backend/core/seamed_router.py`, `seamless_router.py`, `section_router.py`.
- Regression gate: `backend/core/scaffold_invariants.py` (+ the `ROUTING_ENTRY_POINTS` list —
  new routing paths must register here, per `memory/project_hinge_autoscaffold.md`).
- Read FIRST: `memory/project_autoscaffold_single_strand.md` (ISSUE-8: uniform sub-bundles + 2-opt
  splice — the single-strand routing work is already in progress), then `project_seamless_router.md`
  (Hamiltonian search: visit budget, pruning, the load-bearing degree tiebreaker).

## Goal & first steps
1. Reproduce + characterize: which cell-adjacency-graph property predicts failure (no Hamiltonian
   path? odd cell count? cut vertices?). Instrument the seamed router to log where it gives up /
   falls back to per-helix.
2. Decide scope with the user before implementing a router change.

## Hard constraints (this codebase)
- **DNA topology / scaffold routing: ask the user first, implement nothing on a hunch.** Reasoning
  about polarity/traversal/path direction alone reliably produces wrong results here (CLAUDE.md).
- The `_PHASE_*` constants in `lattice.py` are LOCKED — do not touch.
- Every backend change runs `just test` before "done". Add a regression to `scaffold_invariants.py`.
- Don't try to "fix" by post-hoc merging disjoint scaffolds without understanding the router's intent.
