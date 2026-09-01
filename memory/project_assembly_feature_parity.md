---
name: assembly-feature-parity
description: "Binding architecture and acceptance rule: assembly mode matches individual-part behavior comprehensively, with only explicit ownership, assembly-semantic, or measured scale adaptations."
type: project
status: active
authority: canonical
review_after: 2027-02-28
---

# Assembly Feature Parity

## Binding product rule

Assembly mode is a different host and scaling regime, **not a reduced product tier**. Unless the user
explicitly narrows scope, requests such as “port X to assemblies,” “make the assembly X tab the same,”
or “support X in `.nass`” mean comprehensive parity with individual `.nadoc` editing.

“Same” covers the entire behavior, not just the visible panel:

- controls, ordering, labels, help, defaults, presets, advanced options, and enable/disable rules;
- target selection, validation, warnings, confirmations, errors, and recovery;
- start/stop/cancel/resume/retry flows, progress, status, logs, results, and stale-result handling;
- visualization, coloring, overlays, selection, camera interaction, and representation behavior;
- mutations, undo/redo, feature history/seek/delete, autosave, save/reload, and session recovery;
- export and downstream consumers, including simulation preparation, job identity, archives, and cleanup;
- keyboard/menu entry points, accessibility-relevant state, and empty/loading/failure states.

A narrow port of the obvious buttons does not satisfy a parity request. Begin with an inventory of the
existing part behavior and trace every frontend, API, state, persistence, worker/job, visualization,
and test path it uses. The parity inventory is the implementation checklist and acceptance contract.

## Architecture: one capability, two hosts

Prefer this dependency shape:

```text
shared feature/domain logic
        |
        +-- design host: active Design -> design mutation/job API -> design refresh
        |
        `-- assembly host: selected target(s) -> instance/source or assembly API -> source/instance refresh
```

Do not fork business logic merely because `assemblyActive` differs. Extract or reuse a shared domain,
controller, panel model, job builder, validation function, or renderer primitive, then supply thin host
adapters for target lookup, API commit, cache invalidation, and layout. Frontend layout may differ to
accommodate instance/source selection or assembly controls, but capabilities and semantics remain equal.

An existing `if (assemblyActive) return`, disabled control, absent assembly endpoint, stub, or “part-only”
memory statement means **unported work by default**, not a durable product restriction. Remove or replace
the guard when implementing parity. Historical project notes yield to this canonical rule unless they
record a still-valid concrete exception.

## Mutation ownership: decide explicitly

For features that mutate `Design` data, use the same mutation logic as the part editor. Assembly wiring
must make the target semantics explicit:

1. **Shared-source edit** — update the source `.nadoc`; refresh every instance referencing that source.
   This is the default when assembly parts intentionally share a reusable definition.
2. **Instance-only edit** — fork the source or use a true `.nass` instance override when the capability
   has defined override semantics. Never pretend an instance-local change exists by mutating a shared
   source invisibly.
3. **Assembly-owned edit** — transforms, joints, groups, configurations, cross-part relationships, and
   other genuinely assembly-level state belong in `.nass` and use assembly undo/history/persistence.

If user intent does not distinguish shared-source from instance-only and the choice would materially
change other instances, surface that choice. This is an ownership question, not a reason to omit the
feature. Existing infrastructure already supports resolving an instance `Design`, replacing it through
`PATCH /assembly/instances/{id}/design`, invalidating geometry, and re-resolving affected mates.

## Permitted differences and required handling

Parity may be adapted only for a concrete reason:

- **Scale/performance:** molecule or instance count makes the part implementation prohibitively slow or
  memory-heavy. Use batching, shared GPU instancing, level of detail, streaming, aggregation, background
  jobs, target subsets, or explicit limits while preserving the same scientific meaning and workflow.
  Prefer measured thresholds; do not infer “assemblies are large” from the file type alone.
- **Different ownership:** behavior must target a source, one instance, selected instances, or the whole
  assembly. Add a clear target control and deterministic default.
- **Assembly semantics:** cross-part topology, joints, transforms, periodicity, or combined export require
  additional interpretation. Extend the behavior; do not silently drop the difficult parts.
- **Layout:** controls may move or condense, but remain discoverable and functionally equivalent.

For every exception, the implementation and completion report must state the concrete constraint, the
observed or expected failure without adaptation, the chosen closest-equivalent behavior, and any residual
gap. A silent no-op, hidden control, generic “unsupported in assembly mode,” or partial result is not an
acceptable adaptation.

## Example: “make the Simulate tab the same for assemblies”

This means auditing and carrying over every engine and engine-specific option; availability checks;
system/target selection; preparation and validation; advanced parameters; run/stop/resume/retry;
local, cluster, and remote submission where applicable; progress, logs, metrics, trajectory controls,
staleness, visualization, downloads/archives, deletion, and session recovery. It also requires checking
the generated scientific input and provenance—not merely rendering matching cards.

Assembly-specific design work may include choosing one part, selected parts, or the assembled system;
namespacing cross-part topology; estimating atom/bead counts before launch; streaming large outputs; and
using scalable renderers. Those are adaptations within the parity request. If a whole-assembly engine is
scientifically undefined or exceeds a measured resource boundary, preserve part-target execution where
valid, explain the boundary, and expose the closest meaningful workflow instead of omitting the engine.

## Verification contract

Parity work requires tests at the shared core and both host seams. Add at least one comparison test that
drives equivalent part and assembly targets and compares the relevant normalized result. For visual or
interactive behavior, exercise both modes in the running app. For simulation/export, compare generated
inputs, resolved options, provenance, lifecycle state, and result loading—not just API status or DOM
presence. Scale adaptations also need a representative large assembly check and an explicit threshold or
benchmark when performance is the reason for divergence.

Completion reports must include a parity inventory marked complete/adapted/deferred. “Deferred” is allowed
only when the user narrowed scope or a concrete blocker remains; it must not be used to quietly redefine a
comprehensive parity request.

## Related current architecture

- `project_assembly_part_context.md` — selected-instance design fetch/patch patterns.
- `project_path_to_thousands.md` — shared-renderer and large-assembly constraints.
- `project_assembly_configurations.md` — assembly-owned poses/configurations/overrides.
- `frontend/src/ui/file_io.js::savePartToAssembly` — existing design-to-instance save-back seam.
- `backend/api/assembly.py::patch_instance_design` — source replacement, cache invalidation, mate resolve.
