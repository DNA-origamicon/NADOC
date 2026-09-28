# Assembly sharing audit — 2026-09-27

Scope: compare assembly presentation sharing with native `.nadoc` part sharing,
including prepared downloads, publication on an existing invitation, and guest
reconstruction. This is presentation sharing, not collaborative topology editing.

## Findings and fixes

1. **Default assembly renderer could not be exported.** Its custom shaders read
   placement, primitive transform, visibility, and color textures; ordinary
   `instanceMatrix` holds a collapsed identity. The prepared exporter rejected
   those shaders. Added explicit renderer-owned material contracts and a CPU
   snapshot adapter. It composes placement × primitive matrices, respects the
   current LOD offset/count and hidden rows, and copies primitive colors. Close
   geometry, cylinder/bond segments, hulls, hull markers, curved cylinders, and
   atom impostors use these contracts. Surface instances already use standard
   matrices. Sphere impostors retain their radius and the existing guest shader.
   The adapter reads display data only and uses the existing package format.
   Unknown or subsequently replaced shaders still fail closed.
2. **Texture-only edits were absent from sharing change detection.** Fingerprints
   now include the registered texture contents and LOD offsets. Redundant upload
   versions do not republish unchanged content. Actual placement/color/visibility
   changes can update the existing invitation without toggling camera sharing.
3. **Inactive assembly names could title part exports.** Title and open-document
   validation now use the active mode.
4. **Assembly navigation used the last part's axes.** Prepared assembly navigation
   now uses each visible instance's source axes transformed into world space,
   excluding hidden instances and hidden groups.
5. **No browser regression exercised production assembly sharing.** Added a
   two-instance, file-source assembly test using a checked-in small `.nadoc`
   fixture, the default shared renderer, the actual Sharing dialog, and the
   standalone guest loader. It intercepts only hosting transport.

## Parity matrix

| Behavior | Assembly status / evidence |
| --- | --- |
| Enable invitation / prepared snapshot | Same sharing UI, capability gate, transport and package loader as parts; production assembly browser regression |
| Instance placement, visibility, colors | Texture adapter, round-trip unit tests, browser transform/visibility updates |
| Full / cylinders / hull | Registered close, segment and hull paths; browser representation changes |
| Atomistic / surface | Registered atom centers/colors/radii and bond segment transforms; standard surface matrices; atom adapter unit test |
| Add/delete parts and assembly revisions | Existing immutable assembly tracking; browser duplication/deletion and revision isolation unit test |
| Selection / deselection / ping | Existing assembly target resolver and common guest overlay; browser regression |
| Group, cluster, overhang selection | Existing group coverage plus new cluster/overhang world-coordinate tests |
| Independent guest camera | Common revision loader; browser pose assertions with numerical tolerance |
| Presenter follow, guest perspectives, reconnect, room lifecycle | Shared document-agnostic components; existing sharing/presentation tests |
| View tools, annotations, simulation labels, overlays | Common prepared scene metadata and compatibility contracts; existing part regressions protect this path |
| Document/job privacy | Existing context boundaries retained; new assembly → part / other-assembly unit test |

## Boundaries

- Assembly annotation authoring is disabled by the existing annotation subsystem
  (`partMode = !state.assemblyActive`). This audit does not add a new assembly
  annotation data model or expose annotations from the inactive part.
- Prepared sharing publishes complete snapshots. Native assembly animations are
  sampled through the existing poll/export cycle, not streamed at render rate.
- The adapter expands GPU texture instancing into standard instance buffers.
  Very large assemblies remain subject to existing package size/memory limits;
  this work does not establish a large-assembly throughput guarantee.
- Presenter selection is communicated through the existing selection cloud and
  ping. The assembly shader's extra post-lighting selection brightening is not
  baked into scientific strand colors.
- Browser checks use local intercepted transport. Public DNS/TLS and a second
  physical device were not exercised.

## Validation

- Focused final regression run: **71 passed** across assembly export adapters,
  navigation, selection resolution, export metadata, native sharing, view tools,
  and the unchanged PEG/oxDNA live-controller suite.
- Full `just test-frontend`: **7,087 passed, 1 skipped, 1 failed** (546 files).
  The failure was the unchanged PEG live-controller test's 30 ms wait for its
  first frame (`oxdna_live_controller.test.js:183`). Its complete 34-test file
  passed in the focused rerun. Earlier task-related failures were fixed before
  this final run; no sharing test failed in the final full run.
- Production Vite build passed (existing large-chunk advisory only).
- `git diff --check` passed.
- Browser: production assembly sharing passed twice on the final implementation;
  part design-edit sharing also passed. Final combined browser regression:
  **3 passed** (assembly, part representations/volumes/overlays, part selections/
  pings), plus the separate passing part design-edit test.
- Final artifact check: no `__e2e__` files remain within the workspace paths
  used by these tests. Teardown removed three final-run workspace artifacts and
  one project revision store; Playwright output/report directories are absent.

Artifact inventory: browser-created parts/assemblies use `__e2e__` names;
`e2e/global-teardown.js` removes these and their project history even on failure.
The test creates no public rooms, credentials, screenshots outside Playwright,
or simulation jobs. The configured cleanup reporter removes traces/screenshots.
