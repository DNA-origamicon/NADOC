---
name: Dumbbell autoscaffold — in-progress bug fix
description: 10-6-10hb dumbbell autoscaffold crossover bugs; tests pass but visual result still wrong
type: project
originSessionId: b9e1d3af-a80f-454f-b4b3-cfc80c55c3bb
---
## Design: `workspace/10-6-10hb.nadoc`

6 core helices × 168 bp (bp 0–167), 4 outer helices with scaffold only at near cap (bp 0–41) and far cap (bp 126–167). Gap bp 42–125 has no scaffold.

Goal: `auto_scaffold(design, mode="seam_line", scaffold_loops=True)` → one continuous scaffold strand, crossovers only at valid HC scaffold positions, near-side loops extending to negative bp.

---

## All code changes made (2026-04-27, kinematics-cleanup, `backend/core/lattice.py`)

### 1. `_HC_SCAF_VALID` — scaffold crossover positions
Added constant: `frozenset({1,2,4,5,8,9,11,12,15,16,18,19})` (bp%21 positions).
Used in `_expand_helices_for_seam` extension logic and `_build_seam_line_domains` candidate filter.

### 2. `_expand_helices_for_seam` — exterior extensions for outer-cap virtual helices
Per-segment logic for each outer helix's coverage regions:
- **Exterior lo (near-cap seg 0):** scan backward from orig_lo, find first valid scaffold crossover >3 bp away → new lo_bp (e.g., bp -5 for near-cap starting at bp 0)
- **Interior hi (near-cap seg 0):** scan forward from orig_hi, find first valid crossover >3 bp away that is still < next_seg_lo → new hi_bp (e.g., bp 46)
- **Interior lo (far-cap seg 1):** scan backward, same logic → e.g., bp 121
- **Exterior hi (far-cap last seg):** scan forward → e.g., bp 172

### 3. `_assemble_dumbbell_path` — ID-suffix classification + direction constraints
**Classification change:** Switched from Z-range (broke when exterior extensions shifted seg_lo below core z=0) to `_segN` ID suffix: `_seg0`=near, `_seg1`=far, no suffix=core.

**Direction constraints added to orientation search:**
- `near_ord[0]` must be REVERSE — 5' terminal at interior (bp ~46), exterior loop at bp -5
- `far_ord[0]` must be FORWARD — enters from interior bridge (~bp 121), exits to exterior (bp 172)
Uses `_scaffold_direction_from_helix_id(virtual_to_real.get(virt_id, virt_id))`.

### 4. `_build_seam_line_domains` — g_hi bug fix + scaffold validity filter + loop_targets
- **g_hi bug:** Changed `g_hi = g_lo + 1` → `g_lo` for crossover bp. Antiparallel HC transitions now use the same global bp on both helices (DX crossover topology).
- **Scaffold validity filter:** `if _is_hc_pair and g_lo_a % _HC_XOVER_PERIOD not in _HC_SCAF_VALID_SET: continue` — rejects all staple-only crossover positions.
- **`loop_targets` param:** Allows caller to override loop crossover bp for exterior-loop pairs. Values computed in `_route_standard_virt_seg` based on coverage regions.

### 5. `_route_standard_virt_seg` — `loop_targets` computation + dumbbell detection
- `coverage_regions` param added.
- For each outer-cap helix at even path index (loop pair), computes loop_target = first valid scaffold crossover >3 bp from original domain edge in the exterior direction.
- `has_merged_seg` detection: `len(virt_seg) > len({virtual_to_real.get(h.id,h.id) for h in virt_seg})`.
- Calls `_assemble_dumbbell_path` when `scaffold_loops and has_merged_seg`.

---

## Status: Tests pass, visual result still wrong

All 5 dumbbell tests pass (`just test-file tests/test_lattice.py -k "dumbbell"`).
All seam_line tests pass (no regressions).

**Bug persists in the app** — user confirmed after session. Visual result is incorrect; exact failure mode not described before session ended.

---

## How to resume

1. Run `auto_scaffold` on `workspace/10-6-10hb.nadoc` with `mode="seam_line", scaffold_loops=True`.
2. Open cadnano view and describe what's wrong (which helices, which crossovers, what bp values).
3. Add debug logging to `_build_seam_line_domains` and `_assemble_dumbbell_path` to print the assembled path and crossover candidates.
4. Key things to verify:
   - Is `_assemble_dumbbell_path` being entered (has_merged_seg=True)?
   - What is the assembled path order?
   - Are loop_targets being computed and passed?
   - Are crossovers at valid scaffold positions (bp%21 ∈ {1,2,4,5,8,9,11,12,15,16,18,19})?
   - Are near-side crossovers at negative bp?
   - Are both bridge crossovers present (one near bp 46, one near bp 121)?
