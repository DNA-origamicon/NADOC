# FH-24 Fine Routing history editor contract

U27 implementation checkpoint, October 16, 2026, based on `3ffde3e3`.
**All 22 native child kinds are implemented and software-tested.** Current
accounting is **21/38 complete,17 remaining (8 core,9 parked)**; this closes only
the original FH-24 implementation exit. Desktop/performance remains the already
allocated FH-27/MV-53 exit. Editor and organization rollout gates stay off.
See [validation evidence](validation_fine_routing_history_editor.json).

The source audit below began against `3fb2c61d` without test execution and earned
no completion credit. Its fixed inventory and acceptance contract are retained;
the implementation status here supersedes the original gap descriptions.

The [fixed FH-24 exit](remaining_standard_part_checkpoints.md) is: **Fine Routing
child editors: resize, ligate, nick, crossovers and loop/skips editable through
ordinary UI with downstream replay.** All five families below remain required.
Completing one form, a generic endpoint, or replay tests alone does not close it.
FH-18/FH-23 member movement and FH-26 dependency repair remain their existing
exits; neither is replaced, parked, or narrowed by doing this parallel-safe work.

## Original source-audit gaps (before U27)

[MinorMutationLogEntry and RoutingClusterLogEntry](../../../backend/core/models.py)
already give each child and parent a stable ID. The
[versioned registry](../../../backend/api/part_proof_commands.py) registers all
22 kinds below. [prepare_change](../../../backend/api/part_recipe_edit.py) already
accepts `sub_index`, independently proves the original source, changes one child's
inputs and regenerates later children/features. It rebuilds recovery snapshots
and diffs from execution rather than decoding them as authority.

The [Feature Log panel](../../../frontend/src/ui/feature_log_panel.js) currently
offers child revert/delete, but no child parameter editor. Its action eligibility
still depends on retained recovery/diffs. The ordinary
[client.editFeature](../../../frontend/src/api/client.js) sends only `{params}`
and cannot specify `sub_index`. The generic
[edit popover](../../../frontend/src/ui/edit_feature_popover.js) has no routing
schemas and cannot express the required ordered nested inputs. Existing repair
field editors are not a substitute for ordinary tool-specific history controls.

The [owned recipe host](../../../backend/api/part_ordinary_recipe_recording.py)
currently accepts snapshot pattern/extrusion targets only. The existing
`EditFeatureBody` has design/revision/parent-feature expectations but no child ID.
Generic `change_recipe` is cooperative and publishes through `state.set_design`;
it is not the organized owned-publication transaction to expose for this editor.

## Complete native input inventory

These are the actual saved command keys, not a proposed alternate topology
schema. `_proof_version` is protected contract metadata on every row and omitted
from the editable-input column. Directions use the native `Direction` values
`FORWARD` and `REVERSE`. The editor must preserve optionality/defaults and use the
existing native validation; it must not introduce different routing arithmetic.

| # | Native child kind | Authoring input keys | Identity / semantic notes |
|---|---|---|---|
| 1 | `strand-end-resize` | `entries: [{strand_id, helix_id, end, delta_bp}]` | `end` is `5p` or `3p`; signed native delta. Preserve entry order and native terminal semantics. |
| 2 | `domain-shift` | `entries: [{strand_id, domain_index, delta_bp}]` | Domain ordinal resolves at this child's prefix, not the current final design. |
| 3 | `nick` | `helix_id, bp_index, direction` | Exact native backbone site. |
| 4 | `nick-batch` | `nicks: [{helix_id, bp_index, direction}]` | Execute all requests in order; strict replay rejects failed later/duplicate/terminal targets atomically. |
| 5 | `ligate` | `helix_id, bp_index, direction` | Native same-strand merge or adjacent 3′/5′ strand ligation. |
| 6 | `forced-ligation-create` | `three_prime_strand_id, five_prime_strand_id, is_periodic_seam` | Seam defaults false. Saved `_fl_id` is an output ID, not editable endpoint input. |
| 7 | `forced-ligation-delete` | `fl_id` | Existing junction reference, editable as a target. |
| 8 | `forced-ligation-delete-batch` | `forced_ligation_ids: [id]` | Native deletion uses set membership; do not invent sequential duplicate effects. |
| 9 | `forced-ligation-extra-bases` | `fl_id, sequence` | Empty sequence clears; native bases are A/C/G/T/N, case-normalized. |
| 10 | `crossover-place` | `half_a: {helix_id, index, strand}, half_b: {helix_id, index, strand}, nick_bp_a, nick_bp_b, process_id` | `strand` is Direction. `process_id` is nullable and defaults `manual`; saved UUID `crossover_id` is an output identity. |
| 11 | `crossover-place-batch` | `placements: [{crossover_id, half_a, half_b, nick_bp_a, nick_bp_b, process_id}]` | Same item grammar as single placement; nested crossover IDs identify authored output slots. |
| 12 | `crossover-move` | `crossover_id, new_index` | Here `crossover_id` is an existing target, not an output identity. |
| 13 | `crossover-move-batch` | `moves: [{crossover_id, new_index}]` | Preserve the native batch's original-to-final endpoint behavior and qualified lineage. |
| 14 | `crossover-delete` | `crossover_id` | Existing junction target; native desplice semantics. |
| 15 | `crossover-delete-batch` | `crossover_ids: [id]` | Native set deletion; preserve missing-target refusal. |
| 16 | `crossover-extra-bases` | `crossover_id, sequence` | Existing target; empty sequence clears. |
| 17 | `crossover-extra-bases-batch` | `entries: [{crossover_id, sequence}]` | Preserve input ordering and documented native duplicate handling; do not silently apply a universal batch policy. |
| 18 | `loop-skip-insert` | `helix_id, bp_index, delta` | `delta` is -1, 0 or +1. Native delta 0 can remove a stale out-of-range mark. |
| 19 | `loop-skip-twist` | `helix_ids, plane_a_bp, plane_b_bp, target_twist_deg` | Native target-twist convention and physical feasibility remain authoritative. |
| 20 | `loop-skip-bend` | `helix_ids, plane_a_bp, plane_b_bp, radius_nm, direction_deg` | Native positive radius; direction defaults 0. Do not replace this with deformation curvature parameters. |
| 21 | `loop-skip-clear` | `helix_ids, plane_a_bp, plane_b_bp` | Existing clear interval is `[plane_a_bp, plane_b_bp)`. Saved IDs are a list although the live DELETE route accepts comma-separated IDs. |
| 22 | `loop-skip-clear-all` | `{}` | No user parameters. Present an honest no-input operation summary with existing delete/revert actions; upstream edits still regenerate it. Do not add a fake scope or parameter solely to make a form. |

Field sources: [crud request models and recording calls](../../../backend/api/crud.py)
(`StrandEndResizeRequest`, `DomainShiftRequest`, `NickRequest`, `NickBatchRequest`,
`ForcedLigationRequest`, `PlaceCrossoverRequest`, `PlaceCrossoverBatchRequest`,
`MoveCrossoverRequest`, `BatchMoveCrossoversRequest`, junction delete/extra-base
requests); [loop routes](../../../backend/api/routes_loop_skip.py);
[loop replay](../../../backend/api/part_native_commands.py);
[ligation/junction replay](../../../backend/api/part_ligation_commands.py);
[crossover moves](../../../backend/api/part_crossover_moves.py); and
[resize/shift replay](../../../backend/api/part_resize_commands.py).

`apply-loop-skips` and `auto-crossover` are separate snapshot producers. Their
derived counts/stats are not editable child parameters. Retain them as ordinary
workflow/suffix controls, without relabeling them as new Fine Routing children.
Other minor kinds (joint, color, structural creation, etc.) are not silently
claimed implemented by this five-family editor inventory.

## Closed editor and publication contract — implemented U27

Reuse the owned host with one explicit `routing_edit` family, not an arbitrary
public command/callback selector. The ordinary request targets the
existing `/design/features/{index}/edit?sub_index={j}` route and carries `params`,
`expected_design_id`, `expected_revision`, `expected_feature_id` (parent), and
`expected_child_id`. Both indexes are convenience addresses; exact IDs, selected
subtype and supported proof version are checked against the owned source. The
private worker header repeats that closed binding. These additions are implemented by the source-bound route and owned host.

Use a strict, bounded editor normalizer for the inventory above. Reject unknown
editing fields and attempts to change protected identities; preserve recognized
untouched metadata and old replay meaning. Do not silently discard unknown legacy
definition fields to manufacture eligibility. Validate complete submitted batch
items, including entries later superseded by native duplicate handling. Any
difference between live and saved duplicate/error behavior needs an explicit
characterization, not a blanket uniqueness rule or a changed scientific builder.

The shared lifecycle remains capture → isolated original input proof → selected
child edit → sibling/full-suffix regeneration → exact candidate decode and
structural checks → final source/session/revision/policy/cancellation/deadline
check → one publication and undo. Preserve live presentation and physical-state
separation. Organized publication needs the explicit recipe permit role; do not
broaden lightweight group-edit or generic live-callback permissions. Keep public
strict and organization rollout gates unchanged.

Reuse the current shared work slot, capture/operation/recovery/result budgets and
five-second owned ordinary capture/proof/publication deadline. Do not silently
raise limits or run full proof on field changes. Numerical-prefix timeout remains
an explicit outcome; any connection to the existing numerical job lane requires
its own tested cancellation/receipt binding, not an unbounded synchronous retry.
Response formatting costs remain separately measurable. Return candidate-owned
geometry/revision together through shared adoption, rather than racing a later
independent geometry GET.

The modal owns only an input draft until Apply. Cancel cannot write canonical
state, history or redo. Failed/null/stale responses preserve the draft and show
the diagnostic. A submitted Apply is not cancelled merely because the modal is
closed: use real host cancellation/receipt behavior if exposed, never imply
rollback or automatically retry an unknown publication. Capture document/reset
generation and both feature identities at opening; same-ID resets and later child
replacement must retire stale work.

## Pre-child references and stable output slots — implemented U27

[ReplayPrefix](../../../backend/api/part_recipe_prefix.py) retains the state before
the selected top-level entry and now the selected routing child after executing
the preceding children in that cluster, in order.
Neither the parent pre-state nor the final live design is the selected child's
input state. Reuse independent replay; do not decode stored child diffs to obtain
authoritative choices. Earlier siblings can rename/merge/split the exact terminal
or domain the selected child addresses.

Keep parent ID, child ID and `_proof_version` unchanged. Preserve `_fl_id` and
single/nested crossover creation output IDs. In contrast, `fl_id` and
`crossover_id` on move/delete/sequence commands are input references and must not
be frozen as outputs. The current
[pinned identity helper](../../../backend/core/feature_identity.py) protects every
top-level `crossover_id` and does not protect nested batch placement IDs. Add
editor-specific rules in [part_edit_identity](../../../backend/core/part_edit_identity.py)
and the closed normalizer; leave the pinned factory byte-for-byte unchanged.

Batch creation cannot infer output identity from a new row ordinal. Existing
output slots must retain identity across parameter edits/reordering; any supported
added slot needs one host-authored ID allocated after source admission, and a
removed slot must participate in normal downstream dependency failure/repair.
U27 implements and tests that finite add/remove/reorder contract in the native
editor, including downstream refusal after a referenced output is removed. Do not declare a complete batch editor while silently omitting them,
or let caller-supplied replacement IDs redirect existing downstream references.

## Native and organized behavior to preserve

Do not alter lattice tables, crossover position rules, nick polarity, ligation,
resize/shift contributor tracing, loop/skip calculations, atom placement, models,
numerical pins or goldens. Use the existing registered native executor and its
established reconciliation then pending-ligation retry order. No new minor kind
or model literal is needed for this inventory.

[Organization lineage](../../../backend/core/part_group_lineage.py) already
qualifies resize/shift, nick/ligation, crossover placement/movement/deletion and
loop-skip insertion. The [native gate](../../../backend/api/part_group_organization_gate.py)
originally refused four loop commands (clear, clear-all, twist, bend) and three
extra-base commands (single/batch crossover, forced ligation). Complete organized
FH-24 requires bounded admission and final post-retry ancestry evidence for those
seven roles. U27 supplies that evidence through the conserved-domain adapter,
and also qualifies the existing apply-loop-skips snapshot as a downstream suffix.
Local-looking input changes are not justification for a gate-only
allowlist expansion or for skipping retry.

Two ordinary API hazards identified by the audit were corrected in U27:
loop insert/twist/bend previously built an updated design before recording and
returned it from a callback; crossover movement ran native work outside and again
inside recording, with response scope from the first source. Both now capture
and compute through the existing owned recorder; native calculations are unchanged. Use the established
[routing recorder](../../../backend/api/part_routing_recording.py) ownership
pattern for any necessary correction. Do not hold expensive native work under a
new broad lock or change formulas. Preserve legitimate empty/no-op behavior and
legacy tolerant internal helpers where that is the established contract.

## Qualification matrix and evidence

The table retains the original required acceptance matrix and foundation tests.
U27 adds native51, lineage56, host24, worker38, HTTP60, input73 and ordinary
ownership47 cases, plus 49 focused frontend cases; the full frontend suite passes
9,257 tests with one skip. See the validation record for exact runs and red/green
failures. Desktop/performance and broad backend acceptance remain unqualified.

| Required acceptance | Existing foundation / necessary extension |
|---|---|
| Every listed kind has honest ordinary child-row controls or the explicit no-input clear-all treatment | New actual Feature Log → form → API acceptance for all five families; nested batch fields, target selection, clear/default/omitted values and meaningful failure retention. |
| Editing an early child rebuilds later siblings and a later snapshot/deformation | [test_native_routing_proof.py](../../../tests/test_native_routing_proof.py) covers native commands and nick child editing; extend across the complete inventory with native output parity, stable parent/child/output IDs and later-row failure attribution. |
| Input-only source proof, poisoned/evicted recovery, unchanged unselected history and full downstream rebuild | [test_part_recipe_edit.py](../../../tests/test_part_recipe_edit.py) covers source proof, atomic failures and reused prefix; add owned worker/route child-binding cases and a middle-child prefix where prior siblings change the selected target. |
| Invalid batch/member/terminal/site/reference fails without partial publication, undo or redo loss | [test_part_command_references.py](../../../tests/test_part_command_references.py) and [test_geometry_routing_recording.py](../../../tests/test_geometry_routing_recording.py); extend exact indexed diagnostic paths to editor inputs and preserve native error boundaries. |
| Organized overlapping/domain membership follows final native topology after retry | [test_group_lineage_crossovers.py](../../../tests/test_group_lineage_crossovers.py), [test_group_lineage_resize_pipeline.py](../../../tests/test_group_lineage_resize_pipeline.py), and native lineage controls; add the seven missing gate families and a real pending-ligation survivor case. |
| Loop/skip controls retain native feasibility and clear behavior | [test_native_refinement_proof.py](../../../tests/test_native_refinement_proof.py) and loop cases in native routing proof; cover all five child forms/actions plus later `apply-loop-skips` regeneration. |
| Save/reload, one undo/redo, F0/intermediate/end and actual optimized seek agree | [test_fine_routing_diffs.py](../../../tests/test_fine_routing_diffs.py), resize pipeline history tests and [test_group_organization_diffs.py](../../../tests/test_group_organization_diffs.py); exercise real long-history optimized dispatch, not just a flag on a short fixture. |
| Stale parent/child, document reset, protected loadout, cancellation/deadline and failed response cannot overwrite current work | New shared-host and real-client tests; include same design ID/session replacement and held response after a newer publication. |
| Ordinary drawing tools, scripting/native execution and history edit retain the same routing meanings | Actual small native fixtures, not mocked kernels; source-owned affected scope and full candidate response, no duplicate native execution assumed harmless. |
| Complete workflow and responsiveness | Preserve FH-27's existing desktop/latency/memory and broad-regression allocation. Archive-unavailable/no-browser work does not count as app qualification. Tests alone cannot silently enable gates. |

## Finite implementation order within FH-24

1. Freeze the 22-kind normalizer and identity rules with meaningful red tests,
   including input-versus-output IDs and batch slot edits. Add only the needed
   pre-child reference capture and typed diagnostics; preserve saved replay.
2. Extend the one owned recipe transaction/worker to closed routing-child edits;
   prove exact targeting, full suffix rebuild, failure atomicity and organized
   postprocessing admission. Resolve the concrete live-entry ownership gaps with
   existing recorders where exposed by those tests.
3. Connect one ordinary Fine Routing editor with five family forms, a real child
   Edit entry, source-bound request/adoption and preserved draft/error behavior.
   Eligibility for proved native history must not depend on saved recovery bytes;
   legacy/unverified definitions retain honest existing compatibility behavior.
4. Run the full matrix, qualify actual downstream/undo/reload/cold-proof behavior,
   update capability claims to match delivered controls, and remove only proven
   replaced code. Keep app/performance debt and public gates explicit.

These are implementation steps, not new phases or milestones. The full original
FH-24 exit remains required; no partial-kind checkpoint closes it or transfers
unimplemented core routing to parked scientific/assembly/VR work.

## U27 delivered boundaries and pruning

The closed normalizer preserves native defaults and consumer/output identity
roles. New batch slots receive host UUIDs after source admission; workers accept
only that exact private receipt. Prefix metadata uses a closed graph and strict
JSON types with 30,000-node/2,000,000-byte bounds; operation input retains its 256,000-byte/10,000-node
budget and native routing work is bounded. Full proof is confined to opening and
Apply, with the existing shared slot and five-second deadline. These bounds are
admission limits, not measured responsiveness guarantees.

The host independently proves the original source, edits one exact child and
regenerates all later children/features. Unknown legacy definitions refuse rather
than losing fields. The editor keeps drafts on refusal, retires on source/reset
changes, and exposes no fictitious cancellation of an in-flight Apply. Protected
loadouts require the existing explicit workflow. Output IDs and recovery bodies
remain independent: rebuilt history is sent in full for owned routing, extrusion
and pattern edits so the browser cannot backfill stale stable-ID snapshots.

The duplicated extension request-acquisition wrapper is replaced with one shared
source-bound route; loop entry handlers and crossover movement delegate to the
existing recorder. Legacy recovery readers remain necessary and are retained.
All 22 kinds, organized annotation/realization, actual later native suffixes,
missing downstream outputs, one undo/reload/cold proof and optimized seek are
covered. No molecular algorithm, model, constant, pin or golden is changed.
