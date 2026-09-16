# NAMD hard-surface visibility audit

## Confirmed causes

1. `namd_surface_card.js` required an additional `authorizedId` set only by an explicitly marked row click. Creation, copying, production spawning, automatic restoration, and several public selection calls select a job without that flag. The View surface checkbox remained checked while the independent authorization gate hid both preview and simulation surfaces. Previous unit tests explicitly asserted this unwanted behavior.
2. Surface inheritance stopped at the first non-null `prep_params`, even if that object only contained unrelated child controls. It also required the ancestor to remain in the loaded job list.
3. Polls and websocket updates could update a selected job without refreshing its surface descriptor. Conversely, preview event de-duplication could prevent replay to renderers installed after the initial selection.
4. Enabling the solvent/trajectory controller suppressed the native preview immediately, before any replacement graphene coordinates were available. Ion-path data acquired suppression even if it contained no graphene. Preview reset retained old suppression owners across documents.
5. PEG qualification/slit walls use a separate renderer. Selecting a PEG job did not load that renderer, and its wall planes did not consume View surface changes.

## Corrections

- Every selected job with a saved hard surface now qualifies for display, including automatic and inherited selections. View surface remains the user's visibility preference; selecting a job does not override an explicit hidden preference.
- Preparation inheritance merges the ancestor chain with cycle protection. Job list/detail responses additionally provide cached surface settings from the selected package's own manifest, so a prepared production job can render its saved wall without its ancestor. Legacy Cartesian normals supply missing axis information.
- REST and websocket refreshes update the selected descriptor; websocket records retain package-derived display metadata. A startup replay request initializes listeners installed after the surface card, while unchanged refreshes retain the mesh.
- The solvent renderer acquires suppression when a frame actually supplies graphene and releases it when cleared. Ion paths likewise suppress only while supplying replacement graphene. Document/engine reset clears stale owners; independent owners still prevent overlapping preview and simulation surfaces.
- PEG selection loads its saved initial geometry without requesting a full trajectory. Both slit planes now honor View surface independently of the PEG molecule visibility setting.
- An engine visibility gate prevents background NAMD updates from exposing its surfaces on another engine's tab. Returning to NAMD and selecting a surface job recreates its display.

## Other paths reviewed

- Native preview plane placement, closed versus perforated geometry, multiple layers, both surface-axis signs, and plane/ball/stick representations.
- Simulation graphene extraction and binary decoding: actual carbon sites are transformed with the same frame transform as DNA/solvent, and all carbon sites are transmitted (not a visualization subsample).
- Representation updates, renderer clearing, ion-path group transforms, and overlapping suppression owners.
- Box details: the earlier depth-write correction remains in place for transparent fills, labels and lines, avoiding invisible occlusion masks.
- Deselecting a job, selecting a non-surface job, document clearing, and switching engine tabs. These continue to hide job-owned surfaces.

The display-only changes do not alter simulation force fields, generated coordinates, saved job parameters, or running jobs. A saved initial preview is still used before simulation coordinates are loaded; frame renderers take over when their graphene data is available.

## Verification

Automated coverage includes inherited production selection, partial child settings, missing ancestors, late listeners, same-job refresh, closed charged walls, multilayer walls, plane/ball/stick controls, absent replacement frames, suppression release, and PEG's two-wall visibility. The browser regression uses cube_pore.nadoc geometry with controlled job metadata and compares rendered framebuffer hashes with the surface shown/hidden, rather than relying only on object or checkbox flags. Actual local manifests for relaxation `75af92defc27` and production child `796c568b5690` both resolve the saved -Z surface with an 8 nm pore and 0.1 nm offset.

Validation: 390 frontend unit tests, 22 backend tests, both Chromium Playwright tests, and the production build passed. `git diff --check` is clean. The browser fixtures use controlled job records and do not submit or modify simulation jobs.
