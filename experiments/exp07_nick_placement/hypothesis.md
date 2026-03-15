# Exp07 — Nick Placement Algorithm

## Hypothesis

After autostaple crossover placement, the resulting zigzag strands span multiple helices
and are too long (exp05 will confirm). A nick placement algorithm can break these strands
to produce fragments in the canonical 18–50 nt window.

The optimal nick algorithm for honeycomb designs should:
1. **Target length**: 30–35 nt mean (matching published designs)
2. **Stagger**: adjacent helix break positions offset by ~10 bp (half the 21 bp crossover period)
   to form the canonical "brick wall" pattern
3. **Never create sub-18 nt stubs**: check both sides of each nick candidate before committing

Hypothesis: a simple O(N × H) algorithm — "place nicks every T nt, staggered by T/2 between
adjacent helices" — produces a staple length distribution with >95% of strands in the
18–50 nt window, matching the scadnano canonical example.

## Metric

After applying the nick placement algorithm:
- % strands in 18–50 nt window (target: >95%)
- Mean staple length (target: 28–35 nt)
- % strands < 18 nt (target: <2%)
- Runtime in ms (target: <5ms for 18HB)

## Expected figure

Before/after histogram of staple lengths (exp05 distribution vs. post-nick distribution),
showing the shift from long zigzag strands to tightly controlled ~30 nt fragments.

## Algorithm sketch

```
For each staple strand:
  walk the strand 5'→3'
  track position on current helix + cumulative length
  when cumulative length >= target_length AND we are NOT within 5 bp of a helix boundary:
    place a nick here
    reset cumulative length = 0
  after nick, verify remaining tail >= min_length (18 nt);
  if not, absorb into previous segment (shift nick earlier)
```

The "adjacent helix stagger" emerges naturally if we initialise the starting offset
per helix based on helix direction (FORWARD starts at 0, REVERSE starts at target/2).

## Conclusion goal

Produce a working `make_nicks(design, target_length=30, min_length=18)` function and
benchmark it. If it meets the >95% threshold, integrate into `make_autostaple`.
