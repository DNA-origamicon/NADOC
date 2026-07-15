---
name: scaffold-and-loops
description: Scaffold routing (auto_scaffold, seamless), autostaple, loop/skip topology — modes, hotkey sequence, model.
paths:
  - "backend/core/scaffold*.py"
  - "backend/core/seamless*.py"
  - "backend/core/loop_skip*.py"
---

# scaffold-and-loops

## Scaffold routing

## Entry Points
- **Frontend hotkeys**: `[1]`=Autoscaffold, `[2]`=Prebreak, `[4]`=AutoMerge, `[5]`=UpdateStapleRouting, `[6]`=AssignScaffoldSeq, `[7]`=AssignStapleSeqs
- **Backend**: `backend/core/lattice.py` — `auto_scaffold`, `compute_scaffold_routing`, `_build_seam_line_domains`, `_build_end_to_end_domains`

## API Endpoints
| Method | Path | Effect |
|--------|------|--------|
| `POST` | `/design/auto-scaffold` | Auto-generate scaffold strand (CSP, seam+end crossovers) |
| `POST` | `/design/auto-scaffold-seamless` | Seamless scaffold routing (zig-zag end xovers, HJ bridges for multi-section) |
| `POST` | `/design/scaffold-nick` | Add nick to scaffold at specified bp |
| `POST` | `/design/scaffold-extrude-near` | Extrude scaffold from near helix end |
| `POST` | `/design/scaffold-extrude-far` | Extrude scaffold from far helix end |
| `POST` | `/design/assign-scaffold-sequence` | Assign M13mp18 / p7560 / p8064 |
| `POST` | `/design/assign-staple-sequences` | Watson-Crick complement assignment |
| `POST` | `/design/crossovers/auto` | Place all staple crossovers (seam-excluded, edge-dense) |
| `POST` | `/design/auto-break` | Nick at all ticks, grow to ≤56 (lattice-min 21/24) |
| `POST` | `/design/full-autostaple` | One-click: scaffold seq → nick → crossovers → grow → staple seqs |
| `POST` | `/design/auto-merge` | Merge adjacent staple fragments |
| `POST` | `/design/strand-end-resize` | Resize strand domain endpoints |

## Scaffold Routing Modes
**seam_line** (default): mid-helix seam; positions selected sequentially with direction-consistency constraint across the design. Nick set by adjusting domain start/end bp (NOT `make_nick` call).

**end_to_end**: full-domain concatenation per helix.

## Key Backend Functions (lattice.py)
- `auto_scaffold(design, mode, nick_offset, min_end_margin)` — entry point
- `_helix_adjacency_graph(design, virtual_to_real?)` — builds XY-distance graph
- `_greedy_hamiltonian_path(graph)` — nearest-neighbor path
- `compute_scaffold_routing(design, mode)` — returns ordered helix list + seam positions
- `_build_seam_line_domains(...)` — generates scaffold domains with mid-helix seams
- `_build_end_to_end_domains(...)` — generates full-helix domains

## Scaffold Circularity
Scaffold is a circular plasmid (M13) modeled as linear with 5'/3' nick. Nick = sequence assignment start only. Model is linear even though biology is circular.

## Test Constraints
- Scaffold/staple routing tests valid only for **6HB+ designs** (6 helices minimum)
- 2HB too small — degenerate routing, not exercising real logic
- Use `CELLS_6HB` or `CELLS_18HB` as minimum test fixture

## Scaffold Library
- M13mp18 (7249 nt), p7560 (7560 nt), p8064 (8064 nt) — picker modal in UI
- N-fill for designs larger than scaffold length

## Square Lattice Specifics
- `sq_lattice_periodic_skips(design)` → one skip/48bp/helix, staggered; auto-applied on UpdateStapleRouting

## Auto Crossover (`POST /design/crossovers/auto`)
Thin endpoint `auto_crossover()` → shared core `_place_auto_crossovers(design)` in `backend/api/crud.py` (also used by full-autostaple).
- Places staple DX crossovers at all valid major-groove positions.
- **Seam exclusion only**: skips a site within 7 bp (HC) / 8 bp (SQ) of an internal scaffold **seam** — a *double* scaffold crossover (two scaffold crossovers on the same helix pair at consecutive bps), detected by `scaffold_seam_positions()` in `crossover_positions.py`. Full density is kept at the near/far end caps (single u-turn crossovers are NOT seams).
- **Edge density**: coverage at the nick gap is gated on the *staple's own span*, not the helix bp range, so a crossover at a staple terminus (e.g. bp 0 / len-1) is placed — `auto_scaffold` extends the helix past the staple at the caps, which previously suppressed every edge crossover.
- **Bow deduplication**: `all_valid_crossover_sites` emits both bow-left/right; deduped via `seen_pairs`.
- **Ligation**: post-processing pass AFTER all nicks.
- `_desplice_strands_for_crossover` checks both half orderings for delete_crossover.

## Staple routing / autostaple (`POST /design/auto-break`, `POST /design/full-autostaple`)
The Aksel thermodynamic optimizer was **removed** (2026-06; didn't help, hard to reason about — see `feedback_aksel_abandoned`). Routing is now a simple deterministic pipeline. **Order is load-bearing: nick FIRST, then crossovers, then grow.**

- `full_autostaple_endpoint` (crud.py): assign scaffold seq → `_linearize_staple_precursors` → `nick_all_major_ticks` → `_place_auto_crossovers` → `grow_staples` → assign staple seqs. Nicking before crossover placement assembles crossovers into open chains (no staple cycles), so every crossover stays traversed and none is pruned (preserves full density).
- `make_autobreak(design)` = `grow_staples(nick_all_major_ticks(design))` (standalone `/design/auto-break`). No orphaning ligate cap.
- **`nick_all_major_ticks`** — nick every non-scaffold strand at all major ticks (bp%21∈{0,7,14} HC / bp%32∈{0,8,16,24} SQ); co-linear only, never on a crossover/overhang bp.
- **`grow_staples`** = `make_merge_short_staples` (greedy co-linear merge ≤56) + `_absorb_short_staples`. Lattice minimum = 21 HC / 24 SQ (3 tick-segments).
  - **Merge order favours uniformity**: candidates sorted ascending by (shorter member, combined) — grow the shortest segment via its shorter neighbour, don't top a 49 up to 56.
  - **Rebalance-then-split**: when folding a sub-min fragment would exceed 56, nick the neighbour at the balancing co-linear tick so both pieces land in [min, 56] (reproduces the hand-nick on an over-long seam-bridging run). **56 is a hard cap.**
  - **Anti-sandwich** (`_has_sandwich`): a grow that leaves a RUN of interior domains all shorter than both flanks (e.g. 14-7-7 → 14-7-14, or 14-7-7-7 → 14-7-7-14) is prohibited, enforced in both merge and absorb. If a sub-min fragment can't grow either way without sandwiching, it is left sub-min (anti-sandwich wins).

**Validation invariant** (`validator.py`): a strand free 5'/3' terminus on a crossover half = "Strand nicked at crossover location — non-physical" hard failure.

Pinned by `tests/test_simple_router.py`.

## Diagnostics → [.claude/runbooks/RUNBOOK_SCAFFOLD.md](../runbooks/RUNBOOK_SCAFFOLD.md)

## Loop/skip topology

## Entry Points
- **Frontend**: context menu on domain → loop/skip insert → `api.insertLoopSkip(helixId, bpIndex, delta)`
- **Backend**: `backend/core/loop_skip_calculator.py`, `backend/physics/skip_loop_mechanics.py`

## Model
```python
LoopSkip(bp_index: int, delta: Literal[-1, +1])  # on Helix.loop_skips
```
- `delta = +1` → loop (insert extra base) → undertwisted → outward bend / right-handed twist
- `delta = -1` → skip (remove base) → overtwisted → inward bend / left-handed twist

## API Endpoints
| Method | Path | Body | Effect |
|--------|------|------|--------|
| `POST` | `/design/loop-skip/insert` | `{helix_id, bp_index, delta}` | Insert/remove loop or skip (delta=0 removes) |
| `POST` | `/design/loop-skip/bend` | bend params | Apply bend via loop/skip strain |
| `POST` | `/design/loop-skip/twist` | twist params | Apply twist via loop/skip strain |
| `POST` | `/design/loop-skip/apply-deformations` | — | Convert DeformationOps to LoopSkip entries |
| `GET` | `/design/loop-skip/limits` | — | Min/max loop/skip values |

## Physical Mechanism (Dietz, Douglas & Shih Science 2009)
- B-DNA: 10.5 bp/turn, 34.3°/bp
- 7-bp HC array cells: 240° per cell
- **Skip (−1 bp)**: 6 bp spanning 240° → ~9 bp/turn → overtwisted → left torque + tension → bends **inward** / twists left
- **Loop (+1 bp)**: 8 bp → ~12 bp/turn → undertwisted → right torque + compression → bends **outward** / twists right
- Uniform mods across all helices → global twist (bend cancels)
- Gradient across cross-section → global bend (torsion cancels)

## Integration with Deformation
`compute_loop_skip_deformations(design)` → generates `DeformationOp` entries encoding the strain from loop/skip modifications. These feed into the geometric deformation pipeline in `deformation.py`.

## Test Note
Combinatorial testing needed — known intermittent bug where loop/skip geometry is wrong after certain routing operation sequences. See `RUNBOOK_DEFORMATION.md`.

## Key Files
- `backend/core/models.py` — `LoopSkip`, `Helix.loop_skips`
- `backend/core/loop_skip_calculator.py` — loop/skip deformation computation
- `backend/physics/skip_loop_mechanics.py` — XPBD loop/skip strain mechanics
- `backend/api/crud.py` — `/design/loop-skip/*` routes

## Files to Read
- `backend/core/lattice.py` — `auto_scaffold`, `_helix_adjacency_graph`, `_greedy_hamiltonian_path`, `_build_seam_line_domains`
- `tests/test_lattice.py` — existing scaffold routing tests, CELLS_6HB fixture
- `tests/test_scaffold_geometry.py` — backbone continuity tests

## Related
- `MAP_SCAFFOLD_ROUTING.md` — routing architecture
- `REFERENCE_DNA_TOPOLOGY.md` — scaffold circularity

