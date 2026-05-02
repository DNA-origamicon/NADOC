# Advanced Scaffold Routing Notes

## Goal Snapshot

`workspace/Hinge3_advanced_seamed_goal.nadoc` is a snapshot generated from
`workspace/Hinge3.nadoc` using the current experimental Advanced Seam Routing.
It is the target behavior for the future Advanced Seamless router:

- one scaffold strand across the full hinge design
- no leftover short scaffold strands
- original forced scaffold ligations still represented as strand adjacencies
- legal scaffold-neighbor bridge sites between scaffold blocks

Observed summary for the snapshot:

- input scaffold strands: 30
- output scaffold strands: 1
- output scaffold nt: 6316
- seam crossovers: 2
- advanced bridge crossovers: 30

## What We Learned

The regular seamed router and the first advanced-seamed implementation initially
did the same thing because `auto_scaffold_advanced_seamed()` delegated directly
to `auto_scaffold_seamed()`.

The current advanced-seamed branch now behaves differently. It builds a directed
graph over existing scaffold strands as route blocks, finds a Hamiltonian path
through those blocks, extends only exposed termini as needed, and bridges each
3-prime end to the next 5-prime end with scaffold-legal crossover sites.

This works especially well for `Hinge3.nadoc` because the input topology is
already scaffold-block-like: many scaffold strands plus six manual forced
ligation anchors. The planner can treat the forced-anchor strands as ordinary
blocks with protected internal topology, then connect all blocks into one
scaffold.

The advanced-seamed entry point now uses the safety-net seamed strategy:

- prior auto scaffold routing is cleared for designs without manual forced
  scaffold ligations, then the true seamed pipeline is rerun
- designs with forced scaffold ligations preserve those fixed manual edges and
  route the remaining regions
- when fixed edges or missing legal scaffold crossover sites prevent one-strand
  consolidation, the best valid seamed route is returned with an explicit
  incomplete-routing warning

## Why Hinge3 May Remain Incomplete

Manual forced scaffold crossovers are fixed route edges. They can break the
clean mirrored zig-zag symmetry required by seamed routing. For `Hinge3.nadoc`,
advanced seamed currently preserves the forced edges, routes the remaining
regions with true seamed topology, and reports incomplete consolidation:

- `seam_xovers = 20`
- `near_end_xovers = 12`
- `far_end_xovers = 11`
- output scaffold strands: 8

The warning is intentional: when the router cannot legally consolidate all
scaffold into one strand without violating fixed manual edges or scaffold
crossover tables, the user should be told that routing is incomplete.

## Teeth Fixture Caveat

`tests/fixtures/teeth.nadoc` is not analogous to `Hinge3.nadoc`. The historical
fixture is already a routed seamless fixture:

- scaffold strands: 4
- existing crossovers: 34
- existing crossover process IDs: `auto_scaffold_seamless:bridge`,
  `auto_scaffold_seamless:zig`
- forced ligations: 0

Running the advanced scaffold-block planner on this file is therefore a
rerouting/merge operation over an already routed design, not a fresh route from
painted scaffold blocks. The planner can reduce it to one scaffold strand, but
that is not necessarily the correct behavior for this fixture.

`workspace/teeth.nadoc` may already contain prior auto scaffold routing. Advanced
seamed now clears prior auto scaffold crossovers for unforced designs before
rerouting with true seamed topology. In the current workspace file this produces:

- cleared auto scaffold crossovers: 37
- seam crossovers: 22
- left-edge crossovers: 13
- right-edge crossovers: 6
- output scaffold strands: 19

The router returns an incomplete-routing warning because the best valid seamed
route does not consolidate all scaffold into one strand.

A robust advanced router needs to distinguish:

- fresh scaffold-block designs that should be connected into one scaffold
- already-routed designs that should be preserved or explicitly rerouted after
  removing prior auto-generated scaffold crossovers

## Debugging Caveat

Calling `validate_crossover()` on generated crossovers after they have already
been added to a design reports their slots as occupied by an existing crossover.
That is a false positive for post-hoc auditing unless the generated crossover is
temporarily excluded from the design before validation.

## Next Design Direction

Advanced Seamless should likely own this scaffold-block planner. Advanced Seamed
should either:

- call the same planner only when the user explicitly asks for block-bridge
  routing, or
- reintroduce actual seamed/Holliday-junction placement after the block path is
  known.

Before testing against existing routed fixtures like `teeth.nadoc`, decide
whether the advanced router should preserve existing auto-generated scaffold
crossovers or clear and rebuild them.
