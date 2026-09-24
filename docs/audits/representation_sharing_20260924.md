# Representation, multi-overlay, and view-volume sharing

The existing prepared-scene serializer already supports the visible meshes used
by Hull Prism, Cylinders, mrDNA Coarse, mrDNA Fine, and oxDNA, and volume outlines
and local representation layers. Native sharing now fingerprints the visible scene
and representation rather than only tool/annotation metadata. The document,
selected simulation context, room, and explicit-publication guards remain active.
Camera motion alone does not change that fingerprint.

Multi-overlay exposes its frozen scenes to presentation capture. Version 5
packages identify 1–4 independent child scenes; validation requires exact layer
references. The guest renders them back-to-front by camera-space depth, clearing
depth between layers and retaining each layer's lighting. Opacity and translation
are already encoded in the scene. Replacing/clearing a package restores the normal
render loop. `multi-overlay-v1` prevents publication to an older hosting process.
An existing host needs a restart after its current meeting to use overlays.

Verification:
- Browser test `shared_representations.spec.js` exercises the sharing dialog with
  intercepted transport, loads all five representations, view volumes and a
  three-layer overlay in the standalone guest, and checks browser errors.
- Unit coverage checks matrix/opacity round trips, reversed camera draw ordering,
  malformed metadata, renderer cleanup, compatibility gates and automatic updates.
- No production host or public link is created by these tests. Workspace fixtures
  use `__e2e__` names, with design and revision-store cleanup in global teardown.
- `main.js` LOC delta: 0 (existing export initialization gains two lazy getters).

Guests receive display snapshots, not topology or volume-editing controls. Pixel
parity for large, translucent real-design overlays remains a manual visual check.

Validation results: focused sharing/viewer suite **160 passed, 1 skipped**;
sharing browser exercise **passed**, including automatic representation updates;
`just smoke` **23 passed**; production build and `just lint` **passed**. The full
frontend run reached 6,860 passing tests but failed on an unrelated quantum-dot
image import (`hecz-450.png?inline`, denied ID) and a new export test's unstable
mock store. The mock was corrected and the export/viewer tests pass on rerun.
Manual real-device appearance follow-up: `MV-REPRESENTATION-SHARING`.
