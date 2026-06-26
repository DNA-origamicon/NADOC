---
name: Autostaple / autocrossover / autobreak — resolved bugs and current status
description: History of crossover linking issues and autobreak bugs; most resolved as of 2026-04-11
type: project
originSessionId: ebee5130-b4fe-4931-8053-4e9bd2cfe8a2
---
# Autostaple / Autocrossover / Autobreak Status (2026-04-11)

## Resolved bugs

### 1. min_crossover_gap=7 impossible for HC
HC lattices have only 6bp between crossover (offset 6) and tick mark (offset 7).
**Fix**: Abandoned gap-based avoidance, switched to tick-mark nicking which inherently avoids non-tick crossover positions.

### 2. FORWARD staple nicks off by +1
`make_nick(bp=T)` places gap at `T+1` for FORWARD but `T` for REVERSE.
**Fix**: Direction-aware tick selection: FORWARD checks `(bp+1) % period`, REVERSE checks `bp % period`.

### 3. `_ligate()` doesn't merge adjacent domains
After merge pass ligates same-helix strands, touching domains persisted as two separate domains.
**Fix**: Added `_merge_adjacent_domains()` call in `_ligate()`.

### 4. Circular crossovers never re-ligated after autobreak
`ligate_crossover_chains` skips `s_from == s_to` (circular). After autobreak nicks the strand, halves end up on different strands but never get re-ligated.
**Fix**: Added pass 3 to `make_autobreak`: `ligate_crossover_chains(max_length=60)`.

### 5. Tests only checked inter-domain boundaries
Crossover junction tests missed cross-strand nicks (valid when combined > 60 nt).
**Fix**: Tests now accept three forms: inter-domain boundary, wrap-around, cross-strand nick.

## Current state

- 559 backend tests pass, 0 failures
- Playwright autobreak edge tests pass (6HB at 42, 84, 126 bp)
- All crossover junctions accounted for after autobreak
- All strands ≤ 60 nt after autobreak
- Full staple coverage in first/last 14 bp verified

## Known remaining items

- **Holliday junction visual test** (`crossover_holliday.spec.js` test 2) has a pre-existing bug: accesses `design0.helices` but API returns `{design: {helices: ...}}`. Not related to crossover logic.
- `_SCAF_MARGIN = 7` excludes ~30% of staple crossover sites near scaffold crossovers — intentional but aggressive. May revisit.
