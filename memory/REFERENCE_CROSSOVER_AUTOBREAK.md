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

## Manual placement near a strand end (edge cases)

`_build_place_crossover` (crud.py) — two rules for crossovers placed close to a
strand end (from `workspace/crossover_edge_cases.nadoc`):

1. **Junction-only rejection.** A placement is rejected (422) when either half's
   `(helix, index, direction)` slot is already a **crossover junction** — the
   3′-exit / 5′-entry of a cross-helix domain transition inside a multi-domain
   strand (`crossover_junction_slots()` in `crossover_positions.py`). This blocks
   placing a crossover on top of an existing junction (helices 2/3 case). Free
   strand termini and single-domain helix-end strands are **not** junctions, so
   helix-end u-turn crossovers stay allowed. Slots backed by a recorded
   `Crossover` fall through to `validate_crossover`'s "already occupied" (400).
   The frontend mirrors this via `crossoverJunctionSlots()` in
   `cadnano-editor/element_keys.js` to suppress the clickable number sprite.

3. **Edge-of-coverage rejection (bow side).** A crossover connects material on
   the side its bow points — **bow-right** (the sprite is the upper member of the
   HJ pair; `min(nick_a, nick_b) < index`) toward bp `index+1`, **bow-left** toward
   `index-1`. That bp must be strand-covered on **both** helices, else the crossover
   sits at the extreme edge (rightmost/leftmost bp) with only a stub to connect and
   is rejected (422). Backend derives the bow side from the nick offset (no bow-set
   constant needed); frontend uses `_xoverBowDir(bp, isScaffold)` → `bp + bowDir`.
   Consequence: at a helix's right end only the inward (bow-left) crossover is
   offered, at the left end only the inward (bow-right) one — the outward u-turn bp
   is suppressed. `test_crossover_at_bp0_family` still passes (all its bps bow inward).

4. **Crossover through a same-helix overhang boundary.** The `_nick_if_needed`
   inter-domain guard skips a nick only when the next domain is on a **different**
   helix (a real cross-helix crossover junction). A **same-helix** boundary (e.g. an
   inline-overhang tail continuing on this helix) is NOT a junction — the nick goes
   through, severing the beyond-part into its own strand so the connection bp becomes
   a terminus the crossover can ligate to. Then `_strip_orphan_inline_overhangs`
   clears `ovhg_inline_*` tags from any strand left with no paired anchor domain (an
   inline overhang is a tail on a paired staple; a standalone all-overhang strand is
   just a plain staple). Net: the crossover connects the paired domains and the
   severed overhang becomes a plain length-1 staple. See `crossover_edge_cases`
   helices 1/2 (the bp-0 crossover).

2. **1-nt stub is legitimate.** `_nick_if_needed` has **no** "1-nt stub" guard.
   A crossover one bp short of a strand end nicks normally, connecting the long
   domains and leaving the single-nt stub past the crossover (helices 0/1 case).
   A crossover *exactly* on a free terminus is a no-op via `make_nick`'s
   "terminus" branch. (The old stub guards encoded flawed 1-bp-off reasoning and
   were removed — see `feedback_crossover_no_reasoning`.)

## Staple coverage is the user's intent (auto-placement gate)

Scaffold with no staple opposite it is a **deliberate ssDNA loop** (blunt-end-stacking
suppression), not a hole — at helix ends *and* in the interior (comb/"teeth" designs).
So `_place_auto_crossovers` must never ask "is this unstapled bp an accident?". It asks the
same bow-side question as manual placement (rule 3 above): the bp the bow points toward
(`index+1` if bow-right, `index-1` if bow-left) must carry staple on **both** helices. Every
staple-interval boundary is a legitimate 5'/3' terminus, wherever it sits in the helix; a
nick that lands inside a loop is a no-op. The old global-`[min,max]`-span "coverage hole"
test silently starved every interior-loop crossover — see LESSONS J6 and
`feedback_staples_are_user_intent`.

## What "locked" means in full-autostaple

`_locked_and_overhang_staple_ids` (routes_assign_sequences.py) locks a staple only when it
touches a **forced ligation** — a join autostaple cannot re-derive. A **manual crossover does
NOT lock its staple**: it changes only how staples are *connected*, never where they sit, so
its body is linearized, nicked and woven like any other. The manual crossover itself is safe by
three independent mechanisms — `nick_all_major_ticks` skips every recorded crossover bp, the
placer seeds `occupied` from every existing crossover half (no duplicates), and the closing
`ligate_crossover_chains` rebuilds the junction from the surviving record. Locking on a manual
crossover used to blank ~32 bp × 2 helices of crossovers around any hand-routed staple.

Three tiers: **forced-ligation-locked** (whole strand untouchable) · **overhang** (tip/binder
domains protected, duplex body still woven) · **everything else** (fully re-routable).

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
