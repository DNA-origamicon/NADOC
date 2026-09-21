# Prepared viewer static round-trip — 2026-09-20

This validates the experimental snapshot implementation developed after commit
`978e5dda`. It does **not** certify interactive hardware performance, assemblies,
recorded trajectories, scientific selection, or presentation rooms.

## Evidence

- [Voltron results](roundtrip.json): a 22,629,044-byte package preserves 1,711
  geometries and 195 textures. The editor and standalone viewer produce identical
  800 × 600 PNG bytes at the recorded pose. Protein and nanoparticle objects are
  present. The viewer makes zero editor API requests with those requests blocked.
- [Editor image](editor.png) and [viewer image](viewer.png) show the same full-design
  overview; this is not a close-up inspection of every scientific feature.
- [Small-scene results](small/result.json): native export/open, actual pointer
  orbit, camera reset, and preservation of the current scene after an invalid file
  all pass. Its reference and loaded images are also identical.

The Voltron source file is read without modification. The imported test copy uses
a `__e2e__` identity/name and omits history, so its document hash differs from the
earlier real-GPU fixture hash. The source-file hash and package hash are recorded
separately in the results. The large package is disposable and is not retained in
the repository.

## Completed checks

- Full frontend suite: 476 files, 6,685 tests passed.
- Stateful application smoke suite: 23 tests passed.
- Prepared viewer application check: one small-scene test passed; one opt-in
  Voltron static round-trip test passed.
- Production multi-page Vite build passed (existing large-chunk warning).
- `just lint` passed; this command checks Python with Ruff.

These browser checks use software rendering. A large-scene pointer sequence
previously exceeded its timeout under SwiftShader, despite matching static images.
The final large test therefore validates the static round-trip, while the small
test validates pointer interaction. The source renderer is paused after its
reference image to avoid competing software renderers. These runs provide no FPS
acceptance evidence. An initial frontend-suite run under concurrent software GPU
load hit an existing timing-sensitive test; the subsequent idle full runs passed.

The earlier real-GPU A/B report applies only to the committed decoder extraction.
The new runtime/package path requires a fresh comparison on the visible hardware
browser before its performance gate can pass.

## Reproduce

Run `frontend/e2e/prepared_viewer.spec.js` with the isolated smoke Playwright
configuration. Set `NADOC_PREPARED_FIXTURE` to the absolute path of
`workspace/VoltronCoreArmV2.nadoc` for the large static case. Tests use ports
8001/5174, preserving the user's 8000/5173 servers. Test-owned parts/project
stores are removed by teardown; a final inventory matched the preflight project
entries and found no prefixed workspace artifacts. The source file checksum was
unchanged.

See [usage and remaining gates](../../prepared_viewer.md).
