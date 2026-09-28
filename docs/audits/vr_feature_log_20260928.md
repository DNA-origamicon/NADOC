# VR feature-log parity — 2026-09-28

VR authoring already writes the canonical desktop feature log. This follow-up
adds explicit end-to-end regression coverage, without changing commit behavior.

| VR operation | Canonical feature entry |
| --- | --- |
| Painted honeycomb/square extrusion | `snapshot`, `extrude-frame`, “Extrude frame: 6 cells × … bp” |
| Cluster move/rotate | `cluster_op`, exact saved cluster translation/rotation/pivot |
| Overhang move/rotate | `snapshot`, `nucleotide-transform-batch`, “Move/rotate 7 nucleotides” |
| Individual base move/rotate | `snapshot`, `nucleotide-transform-batch`, “Move/rotate 1 nucleotide” |

Painted extrusion uses `addFrameExtrusion` and `mutate_with_feature_log`; end
continuations use the desktop `addBundleContinuation` API. Cluster VR Confirm
calls the desktop translate/rotate confirmation, and nucleotide VR Confirm uses
the same atomic batch persistence as desktop Confirm. The shared transaction
executor requires a new feature-log entry before acknowledging a successful edit.

The physical ScryWrite tests now assert the feature type, operation kind, label
or saved cluster pose, exactly one appended entry, preservation of prior entries,
and complete log equality in the saved `.nadoc` file and after reopening. Move
cases also compare the complete log after VR Undo with its pre-gesture state.
Snapshot cases require both pre-state and post-state payloads.

The tests expose the desktop Feature Log (reusing its visible column for
extrusion), assert the new row is
visible with its expected text, and retain `desktop-feature-log.png`. This is a
viewing adjustment after the measured VR gesture; it does not alter controller
profiles, tolerances, or input paths. These screenshots establish desktop log
visibility, not physical headset comfort. All runs use temporary generated parts;
no fixture or existing workspace file is edited.

## Validation

- 12/12 move/rotate cases: three scopes × all four human controller profiles.
- 8/8 extrusion cases: honeycomb and square × all four human controller profiles.
- 71 focused browser unit checks passed.
- 111 backend checks passed (nucleotide transforms, feature snapshots/clusters,
  VR extrusion drafts, frame extrusion and continuation).

Evidence: `.development-artifacts/vr-feature-log/moves/` and
`.development-artifacts/vr-feature-log/extrudes-reviewed/`. Reproduce with:

```sh
uv run python -m tools.vr_workflows.move_tour --validate
uv run python -m tools.vr_workflows.extrude_tour --validate
```

The initial extrusion attempt is retained under `extrudes/`. Its extrusion and
feature-log checks passed, but the test opened an extra Feature Log column,
exhausting the sidebar width budget and preventing Visualization from opening.
The subsequent representation selection timed out. The corrected test reuses
the already-visible log row and explicitly checks representation-selector
visibility; no product layout or controller tolerance was changed.
