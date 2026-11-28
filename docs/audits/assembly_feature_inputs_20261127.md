# Assembly feature input review — November 27, 2026

Scope: ordinary assembly feature input editors, including upstream whole-origami
patterns. Parts are edited separately in their source editor. This work does not
port part deformation, source histories, or source definitions into assemblies.

Implementation is isolated in `/home/joshua/NADOC-assembly-editors`, based on
662fc1fd plus the backend/frontend pattern changes from 75d33dac. The shared
checkout and its unrelated uncommitted work have not been merged or overwritten.
Delivery branch: `codex/assembly-editors-and-colors`.

## Inventory

| Assembly feature family | Editable inputs |
|---|---|
| Add/duplicate/update/move instances | Name, rigid transform, duplicate offset, fixed/visibility/representation; operation target where applicable. Source definition is excluded. |
| Joint creation/update and mates | Endpoints, existing cluster/connector references, mate connector fields, alignment transform, axis vectors, joint type/value/limits, speed/pause and driven endpoint. Playback guards are excluded. |
| Connectors | Assembly instance, label, position/normal, existing cluster reference, connection type and clearance. |
| Gears | Joint/endpoint references, ratio, invert, names, anchor capture and patch anchors. |
| Groups | Membership/subgroups, name, duplicate offset, translation/matrix, visibility/representation overrides and expansion. |
| Bindings | Both instance/overhang/subdomain references, binding mode and wildcard policy. |
| Linker connections | Endpoints, attachment ends, type, length/unit, bridge sequence and name. |
| Duplexes | Nested endpoint ranges, driver, bound state, mode/wildcard policy and connection type. |
| Belts/riders | Nested pulley selections, radius/positions, rider references, arc/reference angle, local/world transforms. Belt repetition exposes its recorded copy list and poses. |
| Mate/periodic polymerization | Seed, direction/count and additional patterned instances where the operation supports them. |
| Linear patterns | Whole-instance selection, 1D/2D counts, spacing, direction and custom vectors. |
| Circular patterns | Whole-instance selection, count/angle and axis point/direction. |
| Target-only commands | Delete/ungroup, gear resolve, mate refresh and deterministic linker relaxation expose their recorded operation targets. They do not invent numerical controls. |
| Duplex synchronization | No inputs; no input editor is advertised. |

Schemas derive from the actual request models, with reviewed vector/matrix and
pattern schemas for old untyped request fields. Tests account for every request
field as editable or explicitly excluded. Sources, internal part joint states,
cluster overrides and playback transport cannot be injected through this editor.

The editor supports text, enumerations, booleans, optional/nullable values,
vectors, rigid matrices, nested objects and editable lists. It submits only changed
fields: omitted patch values remain omitted, while explicit nulls preserve their
command semantics (e.g. clearing a joint limit). Target changes never rewrite
output identities. Reference choices use the feature's historical prefix, not the
final document; references from different instances carry owner names. Invalid
cross-references are refused during private replay without live changes.

Input requests bind assembly revision and feature identity. Document changes
close the form or reject its response. Apply uses the existing cancellable job,
independent replay, revision-bound commit and one-step undo path. Saved source
histories remain unchanged by patterns and ordinary assembly input edits.

## Compatibility and boundaries

- New pattern records contain versioned inputs and a retained identity seed.
  Growing a pattern preserves surviving copy identities; removing a referenced
  copy refuses the edit atomically. Both patterns participate in the dependency
  and independent verification paths.
- Old summary-only histories retain their legacy capabilities. Missing historical
  inputs are not synthesized from recovery snapshots or given a proof certificate.
- Existing embedded-part editing entry points elsewhere in the application are
  not removed by this change. The new assembly input editor rejects those kinds;
  broader ownership cleanup and the all-instances source-update workflow remain
  separate implementation work.
- Raw linker-helix/strand routes without recorded command contracts, presentation
  configuration tools, and repair-specific workflows are not made into new
  feature editors. This is an inventory of recorded assembly commands.
- Reference lists and forms have focused functional coverage, not a new
  thousand-instance performance qualification. No scale limits or test guards
  were relaxed.

## Validation

- Final editor/schema/pattern checks: 51 backend tests passed. Earlier surrounding
  replay/dependency/job/action/transaction coverage passed 159/160; the existing
  100 ms capture-budget test failed once and passed alone unchanged. No budget
  was relaxed.
- Frontend: initial 59 focused checks passed; final input form/editor/API/label
  selection passed all 29 (overlapping coverage, 71 unique tests across runs).
- Browser editor flow passed twice, most recently 24.2 seconds: nullable joint
  limit, earlier pattern edit through a downstream copy edit, source preservation,
  dependency refusal, cancellation, reopening and independent proof.
- Source-definition exclusion browser check passed (7.2 seconds). Its initial
  test baseline was corrected to compare the admitted source before/after the
  editor: source admission adds an optional `repair_draft: null` default.
- All 29 app smoke checks passed (4.3 minutes), including saving, assembly exit,
  startup, rendering and session teardown.
- `just lint` and `git diff --check HEAD` pass. `just lint-memory` reports the
  pre-existing missing index entry for `project_oxdna_occupancy_clouds.md`, plus
  22 length warnings; this is not a clean memory-lint result.
- All seven owned browser roots were independently checked absent, including
  failed attempts. No new workspace artifacts remain. Full regression-suite
  debt and large-assembly performance qualification remain unchanged.

## Integration notes

The isolated checkout also needs `backend/core/design_loadout_storage.py`, which
662fc1fd's save route already imports but did not include. Copied byte-for-byte
from the existing shared checkout (SHA-256
`7ca7555accf1d10743187c7786116cc8e8027a676f2e87a89c1290d4c3c1a74f`). No source
loadout behavior was redesigned. The first smoke attempt was stopped on that
missing dependency; its owned root was removed.

Local dependency symlinks (`.venv`, `frontend/node_modules` and
`frontend/trace_webgpu/node_modules`) point at the shared checkout's installed
dependencies. They are environment setup, not implementation files to commit.

Historical reference discovery falls back to recorded prefix replay if recovery
payloads are absent. This does not create a proof certificate; Apply still requires
independent verification. Input loading has a cancellable status dialog. No change
to molecular geometry algorithms, phase constants, or simulation materialization.
