# Exp07 — Nick Placement Algorithm: PASS

## Result: PASS — 100% of strands in 18–50 nt window across all helix lengths

| helix length | before nicks | after nicks | in-range | mean | timing |
|---|---|---|---|---|---|
| 42 bp  | 40% ok, 8–132 nt  | **100%** ok, 18–46 nt  | ✓ | 27 nt | 0.8ms  |
| 84 bp  | 35% ok, 22–168 nt | **100%** ok, 22–48 nt  | ✓ | 30 nt | 1.9ms  |
| 126 bp | 35% ok, 22–252 nt | **100%** ok, 22–44 nt  | ✓ | 29 nt | 3.5ms  |
| 168 bp | 35% ok, 22–336 nt | **100%** ok, 22–48 nt  | ✓ | 31 nt | 4.6ms  |
| 252 bp | 35% ok, 22–504 nt | **100%** ok, 22–44 nt  | ✓ | 30 nt | 7.8ms  |

(With `min_end_margin=9` for the autostaple crossover stage.)

## Algorithm summary

`compute_nick_plan_for_strand(strand, target_length=30, min_length=18, max_length=50)`:
1. Walk strand 5'→3' as a flat list of (helix_id, bp, direction) positions
2. Greedily nick every ~target_length nt, never leaving < min_length nt on either side
3. Stop when remaining tail ≤ max_length (50 nt — canonical upper bound)
4. Return nicks in REVERSE order so applying right-to-left preserves original strand ID

Constraint resolution: `ideal_i = last_break + target_length - 1`; clamped by
`max_i = total - min_length - 1` (right tail guard) and `last_break + min_length - 1`
(left tail guard).

## Key fix from original failure
- Changed stop condition `remaining <= 2*target_length` → `remaining <= max_length(50)`
- This prevents tails of 51–60 nt (which passed the old condition but exceeded canonical max)

## Distribution shape (126 bp design, 77 strands)
- 74% are exactly 30 nt (the greedy target)
- Remaining 26% are 22–44 nt (boundary effects at helix ends)
- All within canonical 18–50 nt window

## Actionable conclusions

1. Integrate `make_nicks_for_autostaple` into `lattice.py` (alongside `make_autostaple`)
2. Update `/design/autostaple` endpoint to run crossover placement + nick placement in sequence
3. Change `min_end_margin` default from 3 → 9 in `compute_autostaple_plan` and `make_autostaple`
4. Add tests: `test_autostaple_strand_lengths_in_range()`, `test_nick_placement_no_short_stubs()`
