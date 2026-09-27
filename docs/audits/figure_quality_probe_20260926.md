# Figure-quality surface probe control — 2026-09-26

Removed the temporary eight-iteration smoothing comparison. Figure quality keeps
four Taubin iterations and now honors the probe slider for both native designs
and simulation frames. Its default remains 0.14 nm; standard remains 0.28 nm.
Each preset remembers its own radius during the page session. Figure-quality
regeneration occurs on slider release, and superseded native requests cannot
overwrite the newest mesh. The slider uses 0.01 nm steps. `main.js` LOC delta: 0.

Grid resolution, atomic radii, smoothing, native strand grouping, and simulation
shell grouping are unchanged. Benchmark callers now request the preset default
explicitly by passing `None`, rather than the formerly ignored 0.28 nm value.

## Smoother surfaces: next candidates

- A larger probe fills narrow grooves and reduces small-scale detail. A smaller
  probe generally increases detail/bumpiness. Compare 0.20–0.24 nm with 0.14 nm.
  See [ChimeraX surface documentation](https://www.cgl.ucsf.edu/chimerax/docs/user/commands/surface.html).
- Finer underlying grid sampling reduces discretization artifacts; subdivision
  of an existing mesh alone does not recover shape. Halving grid spacing costs
  approximately eight times the voxels for a fixed volume. NADOC currently targets
  0.05 nm with adaptive coarsening, binary occupancy, and voxel-rounded centers.
- A continuous field before extraction is a candidate for reducing quantization.
  A Gaussian envelope could provide a separate rounded presentation option, but
  changes the surface definition and should not silently replace SES.
  [VMD QuickSurf](https://www.ks.uiuc.edu/Research/vmd/current/ug/node73.html)
  documents this alternative and its quality controls. Neither alternative was
  implemented in this change.

## Verification

- Frontend: 543 files, 7,076 tests passed, one skipped.
- Browser/app smoke: 24 passed. The probe comparison rendered a 6-helix, 21-bp
  design at standard 0.28 nm and figure 0.14, 0.24, and 0.10 nm, then restored
  both defaults. Entire binary meshes matched the independent pre-optimization
  algorithm at each radius; rendered pixels changed with probe and restored
  exactly at 0.14 nm. No page or shader errors. Temporary screenshots were
  inspected and deleted; owned document/session/project/report artifacts cleaned.
- `just test-smart` selected FAST and deferred FULL because the user-opened test
  session had expired. FAST: 9,250 passed, 15 skipped, eight failures, all present
  in the recorded startup-default baseline (seven photoproduct review and one
  CPD snapshot test). No new failing test IDs.
- Timing triage: the new route regression initially took 5.51–5.8 seconds doing
  four fine surface builds across six helices. Reduced it to a real single-helix,
  three-bp fixture on CPU, retaining default/override and JSON/binary assertions.
  Focused execution passed in 0.81 seconds of test time. Full browser geometry
  coverage retains the larger six-helix fixture.
- Final `just test-fast` rerun: 9,250 passed, 15 skipped, the same eight baseline
  failures, 100.77 seconds; zero per-test timing violators.
- Lint and `git diff --check` passed. No production simulation was launched.
