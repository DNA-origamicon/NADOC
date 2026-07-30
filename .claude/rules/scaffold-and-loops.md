---
name: scaffold-and-loops
description: Scaffold routing (seamed/matched/seamless routers, section dispatch), autostaple, loop/skip topology — routes, hotkeys, model.
paths:
  - "backend/core/seamed_router.py"
  - "backend/core/seamless_router.py"
  - "backend/core/section_router.py"
  - "backend/core/scaffold*.py"
  - "backend/core/crossover_positions.py"
  - "backend/core/loop_skip*.py"
  - "backend/physics/skip_loop_mechanics.py"
  - "backend/api/routes_scaffold_routing.py"
  - "backend/api/routes_loop_skip.py"
---

# scaffold-and-loops

*Symbol-by-symbol re-verified 2026-07-30 (`/audit-plan`). The pre-2026-07 `lattice.auto_scaffold`
CSP/seam_line router this file used to document is **deleted** — see "Removed API" at the bottom
before trusting any older doc or script that names it.*

## Scaffold routing

### Entry points
- **Frontend hotkeys** (cadnano editor only — the 3D app binds no digit keys): `[1]` Autoscaffold,
  `[2]` Full Autostaple, `[4]` Add Loops/Skips (`menu-seq-update-routing`), `[5]` Assign Scaffold
  Sequence, `[6]` Assign Staple Sequences. `3`/`7`/`8`/`9`/`0` unbound. Auto-Crossover and
  Auto-Break are deliberately hotkey-less (subsumed by `[2]`). Bound in **two** places that must
  stay in sync: [cadnano-editor/main.js:1436-1442](frontend/src/cadnano-editor/main.js#L1436-L1442)
  (the live keydown handler) and [ui/keyboard_shortcuts.js:392-397](frontend/src/ui/keyboard_shortcuts.js#L392-L397)
  (the help-registry labels).
- **Backend**: [routes_scaffold_routing.py](backend/api/routes_scaffold_routing.py) →
  `seamed_router` / `seamless_router`, dispatching into `section_router` for multi-section helices.

### The three routers (this is the whole scaffold-routing surface)
| Route | Handler | Core fn |
|---|---|---|
| `POST /design/auto-scaffold-seamed` | [routes_scaffold_routing.py:86](backend/api/routes_scaffold_routing.py#L86) | [`seamed_router.auto_scaffold_seamed:1224`](backend/core/seamed_router.py#L1224) |
| `POST /design/auto-scaffold-matched` | [routes_scaffold_routing.py:112](backend/api/routes_scaffold_routing.py#L112) | [`seamed_router.auto_scaffold_matched:1305`](backend/core/seamed_router.py#L1305) |
| `POST /design/auto-scaffold-seamless` | [routes_scaffold_routing.py:140](backend/api/routes_scaffold_routing.py#L140) | [`seamless_router.auto_scaffold_seamless:111`](backend/core/seamless_router.py#L111) |

- **seamed / matched share one implementation**: [`_auto_scaffold_seamed_impl:512`](backend/core/seamed_router.py#L512).
  `matched` = the matched-ends variant (far-crossover-LEFT user rule; see `project_autoscaffold_single_strand`).
- **Multi-section dispatch**: both routers call [`section_router.route_sections:354`](backend/core/section_router.py#L354)
  when [`has_multisection_helix:77`](backend/core/section_router.py#L77) is true. `section_router` is
  never reached directly from a route.
- **Helix ordering** = Hamiltonian path search, not a greedy nearest-neighbour walk:
  [`_ham_path_search:195`](backend/core/seamed_router.py#L195) under budget
  [`_HAM_PATH_BUDGET:192`](backend/core/seamed_router.py#L192), adjacency from `_build_adj:159`,
  wrapper `_hamiltonian_path:280`. `seamless_router._ham_path_ending:68` delegates to it.
- **Valid scaffold-crossover bp** = exact modular residue sets, NOT a ± tolerance window:
  [`_HC_SCAF_BOW_RIGHT:40`](backend/core/seamed_router.py#L40) + `crossover_positions.py` over
  `HC_SCAFFOLD_CROSSOVER_OFFSETS` / `SQ_SCAFFOLD_CROSSOVER_OFFSETS`
  ([constants.py:259/285](backend/core/constants.py#L259)).
- Also live: `auto_scaffold_seamed_bounded:1292`, `seamed_routability_errors:1149` (pre-flight
  failure reasons surfaced by the routes), and `POST /design/route-for-polymerization`
  ([routes_scaffold_routing.py:164](backend/api/routes_scaffold_routing.py#L164)).

**Regression gate**: [scaffold_invariants.py](backend/core/scaffold_invariants.py) —
`scaffold_routing_invariants:86` + `MIN_SSDNA_MARGIN:40`. The three entry points are swept by the
`ROUTING_ENTRY_POINTS` parametrize list in
[tests/test_scaffold_invariants.py:53](tests/test_scaffold_invariants.py#L53) (it lives in the
test, not in the module).

### Other scaffold/sequence routes
| Method | Path | File | Effect |
|--------|------|------|--------|
| `POST` | `/design/assign-scaffold-sequence` | [routes_assign_sequences.py:62](backend/api/routes_assign_sequences.py#L62) | Assign M13mp18 / p7560 / p8064 (or custom) |
| `POST` | `/design/assign-staple-sequences` | [routes_assign_sequences.py:312](backend/api/routes_assign_sequences.py#L312) | Watson-Crick complement assignment |
| `POST` | `/design/full-autostaple` | [routes_assign_sequences.py:345](backend/api/routes_assign_sequences.py#L345) | One-click pipeline (below) |
| `POST` | `/design/crossovers/auto` | [crud.py:3263](backend/api/crud.py#L3263) | Place all staple crossovers |
| `POST` | `/design/auto-break` | [crud.py:5722](backend/api/crud.py#L5722) | Nick at all ticks, grow to ≤56 |
| `POST` | `/design/auto-merge` | [crud.py:5742](backend/api/crud.py#L5742) | Merge adjacent staple fragments |
| `POST` | `/design/strand-end-resize` | [crud.py:2581](backend/api/crud.py#L2581) | Resize strand domain endpoints |
| `POST` | `/design/scaffold-domain-paint` | [crud.py:2315](backend/api/crud.py#L2315) | Paint a domain as scaffold |
| `POST` | `/design/strands/{id}/convert-to-scaffold` | [crud.py:2544](backend/api/crud.py#L2544) | Promote a strand to scaffold |

### Scaffold circularity
Scaffold is a circular plasmid (M13) modeled as linear with 5'/3' nick. Nick = sequence assignment
start only. Model is linear even though biology is circular.

### Scaffold library
M13mp18 (7249 nt), p7560 (7560 nt), p8064 (8064 nt) — [sequences.py:45-57](backend/core/sequences.py#L45).
Picker modal in UI. Designs longer than the chosen scaffold are **'N'-filled**, not rejected
([sequences.py:233,253](backend/core/sequences.py#L233)); the assign call returns `padded_nt` = how
many positions got 'N'.

### Square lattice specifics
`sq_lattice_periodic_skips(design)` → one skip/48bp/helix, staggered —
[loop_skip_calculator.py:926](backend/core/loop_skip_calculator.py#L926), consumed by
[skip_twist_tuning.py:25,78,205](backend/api/skip_twist_tuning.py#L25).

## Auto crossover (`POST /design/crossovers/auto`)
Thin endpoint `auto_crossover()` ([crud.py:3264](backend/api/crud.py#L3264)) → shared core
`_place_auto_crossovers(design)` ([crud.py:3309](backend/api/crud.py#L3309)), also imported by
[routes_assign_sequences.py:41](backend/api/routes_assign_sequences.py#L41) for full-autostaple.
- Places staple DX crossovers at all valid major-groove positions.
- **Seam exclusion only**: skips a site within `seam_margin` = 7 bp (HC) / 8 bp (SQ) of an internal
  scaffold **seam** — a *double* scaffold crossover (two scaffold crossovers on the same helix pair
  within `_SEAM_BP_WINDOW` = 1 bp), detected by
  [`scaffold_seam_positions:152`](backend/core/crossover_positions.py#L152). Full density is kept at
  the near/far end caps (single u-turn crossovers are NOT seams).
- **Edge density**: coverage at the nick gap is gated on the *staple's own span*, not the helix bp
  range, so a crossover at a staple terminus (bp 0 / len-1) is placed — the routers extend the helix
  past the staple at the caps, which previously suppressed every edge crossover.
- **Bow deduplication**: [`all_valid_crossover_sites:89`](backend/core/crossover_positions.py#L89)
  emits both bow-left/right; deduped via the local `seen_pairs` set (crud.py:3405).
- **Ligation**: post-processing pass AFTER all nicks (`ligate_crossover_chains`).
- `_desplice_strands_for_crossover` ([crud.py:2840](backend/api/crud.py#L2840)) checks both half
  orderings for delete_crossover.

## Staple routing / autostaple (`POST /design/auto-break`, `POST /design/full-autostaple`)
The Aksel thermodynamic optimizer was **removed** (2026-06; didn't help, hard to reason about — see
`feedback_aksel_abandoned`). Routing is now a simple deterministic pipeline. **Order is load-bearing:
nick FIRST, then crossovers, then grow.**

- `full_autostaple_endpoint` ([routes_assign_sequences.py:346](backend/api/routes_assign_sequences.py#L346)
  — moved out of crud.py by the carve-up): assign scaffold seq → `_linearize_staple_precursors:216`
  → `nick_all_major_ticks` → `_place_auto_crossovers` → `grow_staples` → assign staple seqs. Nicking
  before crossover placement assembles crossovers into open chains (no staple cycles), so every
  crossover stays traversed and none is pruned (preserves full density).
- `make_autobreak(design)` = `grow_staples(nick_all_major_ticks(design))`
  ([lattice.py:2343](backend/core/lattice.py#L2343), standalone `/design/auto-break`). No orphaning
  ligate cap.
- **`nick_all_major_ticks`** ([lattice.py:2273](backend/core/lattice.py#L2273)) — nick every
  non-scaffold strand at all major ticks (bp%21∈{0,7,14} HC / bp%32∈{0,8,16,24} SQ); co-linear only,
  never on a crossover/overhang bp.
- **`grow_staples`** ([lattice.py:2389](backend/core/lattice.py#L2389)) = `make_merge_short_staples`
  (:2580, greedy co-linear merge ≤56) + `_absorb_short_staples` (:2419). Lattice minimum = 21 HC /
  24 SQ (3 tick-segments).
  - **Merge order favours uniformity**: candidates sorted ascending by (shorter member, combined) —
    grow the shortest segment via its shorter neighbour, don't top a 49 up to 56.
  - **Rebalance-then-split**: when folding a sub-min fragment would exceed 56, nick the neighbour at
    the balancing co-linear tick so both pieces land in [min, 56]. **56 is a hard cap.**
  - **Anti-sandwich** (`_has_sandwich`, [lattice.py:2117](backend/core/lattice.py#L2117)): a grow
    that leaves a RUN of interior domains all shorter than both flanks (14-7-7 → 14-7-14, or
    14-7-7-7 → 14-7-7-14) is prohibited, enforced in both merge and absorb. If a sub-min fragment
    can't grow either way without sandwiching, it is left sub-min (anti-sandwich wins).

**Validation invariant** ([validator.py:206](backend/core/validator.py#L206)): a strand free 5'/3'
terminus on a crossover half = `"Strand nicked at crossover location(s) — non-physical"` hard failure.

Pinned by `tests/test_simple_router.py` (autostaple/anti-sandwich) and `tests/test_section_router.py`
(section/dumbbell coverage).

## Diagnostics → [.claude/runbooks/RUNBOOK_SCAFFOLD.md](../runbooks/RUNBOOK_SCAFFOLD.md)

## Loop/skip topology

### Entry points
- **Frontend**: context menu on domain → loop/skip insert → `api.insertLoopSkip(helixId, bpIndex, delta)`
- **Backend**: [routes_loop_skip.py](backend/api/routes_loop_skip.py) (routes),
  [loop_skip_calculator.py](backend/core/loop_skip_calculator.py) (topology),
  [skip_loop_mechanics.py](backend/physics/skip_loop_mechanics.py) (strain → joint specs)

### Model
```python
class LoopSkip(BaseModel):     # backend/core/models.py:163, on Helix.loop_skips (models.py:133)
    bp_index: int             # absolute bp index within the helix (0-based)
    delta: int                # +1 = loop (insertion), -1 = skip (deletion)
```
`delta` is a plain `int` — **there is no type-level constraint** to {-1, +1}; values outside that set
are simply never produced. Don't assume the model rejects them.

- `delta = +1` → loop (insert extra base) → undertwisted → outward bend / right-handed twist
- `delta = -1` → skip (remove base) → overtwisted → inward bend / left-handed twist

### API endpoints
| Method | Path | File | Effect |
|--------|------|------|--------|
| `POST` | `/design/loop-skip/insert` | [routes_loop_skip.py:46](backend/api/routes_loop_skip.py#L46) | Insert/remove loop or skip (delta=0 removes) |
| `POST` | `/design/loop-skip/twist` | [routes_loop_skip.py:89](backend/api/routes_loop_skip.py#L89) | Apply twist via loop/skip strain |
| `POST` | `/design/loop-skip/bend` | [routes_loop_skip.py:142](backend/api/routes_loop_skip.py#L142) | Apply bend via loop/skip strain |
| `GET` | `/design/loop-skip/limits` | [routes_loop_skip.py:197](backend/api/routes_loop_skip.py#L197) | Min/max loop/skip values |
| `POST` | `/design/deformation/validate` | [routes_loop_skip.py:244](backend/api/routes_loop_skip.py#L244) | Validate a deformation request |
| `DELETE` | `/design/loop-skip` | [routes_loop_skip.py:284](backend/api/routes_loop_skip.py#L284) | Remove a loop/skip |
| `POST` | `/design/loop-skip/apply-deformations` | [crud.py:11065](backend/api/crud.py#L11065) | Convert DeformationOps to LoopSkip entries |
| `POST` | `/design/loop-skip/clear-all` | [crud.py:11050](backend/api/crud.py#L11050) | Clear every loop/skip |

Note the split: most loop-skip routes moved to `routes_loop_skip.py`, but `apply-deformations` and
`clear-all` are **still in crud.py** — grep both when changing this surface.

### Physical mechanism (Dietz, Douglas & Shih Science 2009)
- B-DNA: 10.5 bp/turn, 34.3°/bp
- 7-bp HC array cells: 240° per cell
- **Skip (−1 bp)**: 6 bp spanning 240° → ~9 bp/turn → overtwisted → left torque + tension → bends **inward** / twists left
- **Loop (+1 bp)**: 8 bp → ~12 bp/turn → undertwisted → right torque + compression → bends **outward** / twists right
- Uniform mods across all helices → global twist (bend cancels)
- Gradient across cross-section → global bend (torsion cancels)

### Integration with deformation
The loop/skip → strain path is
[`twist_loop_skips:555`](backend/core/loop_skip_calculator.py#L555) /
[`bend_loop_skips:734`](backend/core/loop_skip_calculator.py#L734) /
[`apply_loop_skips:890`](backend/core/loop_skip_calculator.py#L890), producing `DeformationOp`
entries ([models.py:1118](backend/core/models.py#L1118), stored on `Design.deformations`) that feed
the geometric deformation pipeline in `backend/core/deformation.py`. The physics-side segment
strain lives in `skip_loop_mechanics.py` (`compute_segment_twist_deficit:82`, `compute_loop_joints:127`).

### Test note
Combinatorial testing needed — known intermittent bug where loop/skip geometry is wrong after
certain routing operation sequences. See `RUNBOOK_DEFORMATION.md`.

## Test constraints
- Scaffold/staple routing tests valid only for **6HB+ designs** (6 helices minimum). 2HB too small —
  degenerate routing, not exercising real logic.
- **`CELLS_6HB` / `CELLS_18HB` are NOT shared fixtures.** Each is separately re-declared in several
  files with *different* cell lists (e.g. `tests/test_helix_neighbors.py:58,61`,
  `tests/test_overhang_geometry.py:47`, `experiments/exp06_exclusion_zone/run.py:16`). Copy the one
  from the nearest comparable test; never assume the name means the same geometry.
- Real routing fixtures live on disk: `tests/fixtures/10-6-10hb_seamed.nadoc` (section/dumbbell).

## Removed API — do not resurrect from old docs
`lattice.auto_scaffold(design, mode="seam_line"|"end_to_end", ...)`, `compute_scaffold_routing`,
`_build_seam_line_domains`, `_build_end_to_end_domains`, `_helix_adjacency_graph`,
`_greedy_hamiltonian_path`, the `seam_line`/`end_to_end` **mode** concept, the CSP router
(`RouterDomain`/`CandidateXover`/`validate_routing`/`seam_tol`/`end_tol` tolerance windows), and the
unsuffixed `POST /design/auto-scaffold` route are **all deleted**. Nothing in `backend/` defines
them. Known stragglers still naming them (logged in `memory/project_tech_debt.md`):
`scripts/inspect_bp0.py`, `scripts/gen_examples.py` (both ImportError on run), and several
`frontend/e2e/*.spec.js` specs POSTing the dead route. `backend/api/headless_build.py:564` defines
its own unrelated `auto_scaffold(...)` facade taking a bool `seamless` — same name, different thing.

## Related
- [REFERENCE_DNA_TOPOLOGY.md](../../memory/REFERENCE_DNA_TOPOLOGY.md) — scaffold circularity/polarity
- `memory/project_autoscaffold_single_strand.md` — section_router, dumbbell, matched-ends rule
- `memory/project_seamless_router.md` — Hamiltonian budget/pruning
- `memory/project_hinge_autoscaffold.md` — hinge/weave routers (`hinge_router.py`, `hinge_weave_router.py`)
