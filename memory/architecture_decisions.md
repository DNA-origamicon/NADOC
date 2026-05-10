# Architecture Decisions

## DTP-PMD-1: Periodic MD Is Physical-Layer Only

Periodic MD trajectories may be previewed and tiled back onto the 3D display,
but must not overwrite the topological layer or canonical geometric layer unless
the user explicitly asks for a new physical-state import workflow.

Rationale: the periodic cell represents a bulk-equilibrated repeat unit, not the
literal full design topology. Applying it directly to topology would violate the
topological/geometric/physical separation in `DEVELOPMENT_PLAN.md`.

## DTP-PMD-2: Axial Period Is a Hard Constraint

For honeycomb periodic-cell MD, the axial cell length is exactly
`n_periods * 21 * BDNA_RISE_PER_BP` (`7.014 nm` for one period with current
constants). Any pressure-control workflow must preserve this value unless a
human explicitly decides to study axial strain.

Rationale: the periodic wrap bonds and crossover-repeat assumption are only
geometrically meaningful if the simulated cell remains commensurate with the
21 bp honeycomb repeat.
