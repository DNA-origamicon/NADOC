# oxDNA PEG → NAMD seed handoff

Updated 2026-09-11. Shared surface geometry and read-only PEG source inspection
are implemented. Constructing a PEG-containing NAMD system remains blocked on the
target representation, chemical mapping, force-field assets and validation.
Setup and isolated Live support were previously committed as `e3e9a5a0`.

## Current implementation

| Component | Implemented behavior | Remaining work |
| --- | --- | --- |
| `POST /api/oxdna/peg/namd-seed` | Reviews a source checkpoint and reports missing prerequisites; always returns `launch_ready=false` | Wizard preview and target preparation |
| `peg_seed_source.inspect_peg_job` | Checks frozen DNA topology, complete checkpoint records, PEG chain/graft/terminal identities and source hashes | Target particle/atom assignment |
| Configuration reader | `read_configuration_full_unwrapped` accepts `n_trailing_extra`, preventing appended PEG from shifting DNA indexing | Pass the validated source inventory into the eventual target backmapper |
| Source coordinates | Makes DNA connectivity and grafted PEG chains whole; preserves DNA CM/a1/a3, source identities and graft references | Target-specific molecular reconstruction |
| Shared transforms | Carry DNA, PEG, plane, pore and grafts through one recorded rigid transform, with explicit nm→Å and periodic cell information | Apply the same map to target-specific restraints and external vectors |
| NAMD seed entry points | Reject PEG sources before backmapping or job preparation; never silently discard the coating | Enable only after every target component is mapped and validated |
| Graphene adapters | Preserve coating registration during clearance/recentering and support rotated orthorhombic cell geometry | Scientific validation of the selected surface/coating interactions |

See [shared surface transforms](surface_transforms.md) for the geometry contracts,
representability limits, all six barrier dispositions and verification results.
The original source files and design topology remain unchanged by inspection.

## Direct creation is separate from checkpoint seeding

[Direct NAMD PEG surface drafts](namd_peg_surfaces.md) can now be created and reopened
from File → NAMD PEG Surfaces or the NAMD sidebar without an oxDNA source. They
save support/coating intent and a schematic graft layout. They do not perform the
checkpoint-to-atom mapping described here or attach themselves to simulation jobs.

## Required representation decision

Choose coarse-grained PEG with atomistic DNA, or atomistic PEG and DNA. Current
DNA2PEG beads are statistical segments, not ethylene-oxide repeat units. Atom
counts and chain-end chemistry cannot be inferred from `segments` alone.

A coarse-grained target needs an explicit bead model and PEG–atomistic-DNA cross
interaction model; oxDNA's DNA-center-of-mass WCA interactions cannot be inherited
unchanged. An atomistic target needs chemical chain lengths/end groups, a mapping
from statistical segments, and compatible PSF/PDB/parameter assets with provenance.
Both require explicit graft/terminal assignments and surface interactions.

The local `experiments/peg_namd` research package audits supplied chain/slab
assets; it is not a checkpoint backmapper. Its example registry has null PEG and
surface assets and assumes a gold slab. Those assumptions cannot substitute for
a hard wall or graphene. This research work is maintained separately from the
shared-transform implementation.

## Next implementation sequence

1. Select the target PEG representation and provide compatible topology, coordinate
   and force-field assets, including DNA/PEG/surface cross interactions.
2. Implement the target adapter in an isolated candidate package. Require an
   explicit mapping for every source chain, graft and terminal; report missing
   components rather than dropping them.
3. Produce a source/candidate visual comparison and contact/geometry audit before
   promoting new molecular placement. Preserve existing DNA topology/geometry gates.
4. Add the wizard preview and draft NAMD preparation only when every selected
   component has a complete mapping. Keep source hashes and coordinate provenance.
5. Run molecular backmapping and engine validation in a user-opened
   `just test-session`; exact commands and deferred validation are recorded in
   [surface transforms](surface_transforms.md#6-molecularengine-validation--tests-prepared-session-still-required).

## Verified acceptance cases

- Appended PEG does not change DNA particle identities.
- Every source PEG bead belongs to an explicit chain with checked graft/terminal IDs.
- Partial checkpoints, topology mismatches and inconsistent metadata are rejected.
- Rigid transforms preserve relative geometry and DNA orientations; periodic images
  follow connectivity and recorded grafts rather than independent chain recentering.
- Source files remain byte-for-byte unchanged; their hashes accompany the review.
- Missing target chemistry/mapping produces explicit barriers and blocks NAMD seeding.

Target atom mappings, a PEG NAMD preparation UI and physical validation remain open.
Related inventories: [setup barriers](peg_coating_setup.md) and
[Live implementation](peg_live.md).
