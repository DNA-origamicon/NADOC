---
name: Crossover and autobreak system reference
description: How crossovers, nicks, autocrossover, autobreak, ligation, and circular strands work — load when touching any crossover or autobreak code
type: reference
originSessionId: ebee5130-b4fe-4931-8053-4e9bd2cfe8a2
---
# Crossover & Autobreak System

## Pipeline order

1. **Bundle** — `make_bundle_design()` creates helices with one scaffold + one staple per helix.
2. **Auto-crossover** — `auto_crossover()` in `crud.py` places all valid staple crossovers:
   - For each valid site: nick both helices' staple strands, register crossover record.
   - Then `ligate_crossover_chains()` bulk-ligates all fragments into multi-domain strands.
3. **Autobreak** — `make_autobreak()` in `lattice.py` nicks long strands into ≤60 nt segments:
   - Pass 1: Nick at major tick marks.
   - Pass 2: `make_merge_short_staples()` repairs nicks where merging is safe.
   - Pass 3: `ligate_crossover_chains(max_length=60)` re-ligates previously-circular crossovers.

## Key files

| File | What |
|------|------|
| `backend/api/crud.py` | `place_crossover`, `auto_crossover`, `delete_crossover` |
| `backend/core/lattice.py` | `make_autobreak`, `make_nick`, `_ligate`, `ligate_crossover_chains`, `make_merge_short_staples` |
| `backend/core/crossover_positions.py` | `all_valid_crossover_sites` |

## Tick marks (nick positions)

| Lattice | Period | Tick set |
|---------|--------|----------|
| HC | 21 | {0, 7, 14} |
| SQ | 32 | {0, 8, 16, 24} |

## FORWARD/REVERSE nick asymmetry

`make_nick(helix, bp, direction)` places the gap at boundary `bp+1` for FORWARD, `bp` for REVERSE.

To land the gap ON tick mark T:
- **FORWARD**: nick at `bp = T-1` → check `(bp+1) % period ∈ tick_set`
- **REVERSE**: nick at `bp = T` → check `bp % period ∈ tick_set`

## Crossover junction evidence — three valid forms

After autobreak, every crossover record must be evidenced in the strand graph as one of:

1. **Inter-domain boundary** — consecutive domains within one strand: `d[i].end_bp == ha.index` on helix A, `d[i+1].start_bp == hb.index` on helix B.
2. **3'→5' wrap-around** — same strand's last domain 3' end matches one half, first domain 5' start matches the other. Occurs when `ligate_crossover_chains` skips circular `s_from == s_to`.
3. **Cross-strand nick** — strand A's 3' end matches one crossover half, strand B's 5' start matches the other. They are different strands because merging would exceed 60 nt. Valid topology — the crossover is a nick between two strands.

## Circular crossovers

When `ligate_crossover_chains` finds `s_from == s_to` for a crossover, ligation is skipped (would create a circular strand). After autobreak nicks that strand, the halves may end up on different strands. Pass 3 of `make_autobreak` re-runs `ligate_crossover_chains(max_length=60)` to ligate these if the combined length ≤ 60 nt. If combined > 60 nt, the crossover remains as a cross-strand nick (form 3 above).

## Sandwich rule

No domain pattern `[longer, shorter, longer]` (e.g. 14-7-14). Checked by `_has_sandwich()`. The merge pass also respects this: won't merge if the result has a sandwich.

## `_ligate()` and domain merging

`_ligate(design, s1, s2)` joins s2's domains onto s1's 3' end. It calls `_merge_adjacent_domains()` to collapse same-helix same-direction adjacent domains into one. Without this merge, domain fragmentation breaks crossover junction pattern detection.

## Crossover avoidance during nicking

Autobreak skips any nick position where the bp or tick boundary matches a crossover record position:
```python
if (h_cur, bp) in xover_bps or (h_cur, tick_bp) in xover_bps:
    continue
```

## Testing crossover junctions

When writing tests that verify crossover junctions survive autobreak, check ALL THREE forms. Use terminal lookup maps for the cross-strand nick check:
```python
five_prime[(helix_id, start_bp, direction)] = strand_id
three_prime[(helix_id, end_bp, direction)] = strand_id
```
Then for each crossover, try forward `(ha→hb)` and reverse `(hb→ha)` lookups.
