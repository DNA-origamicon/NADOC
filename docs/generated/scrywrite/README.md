# ScryWrite retained visual evidence

These artifacts are ScryWrite's headset-free projection diagnostics. Regenerate the
canonical asymmetric perspective scenario from the repository root with:

```bash
just scrywrite-evidence
```

- [`chiral_perspective_pov.png`](chiral_perspective_pov.png) shows the scripted tester's
  deterministic 72-degree POV.
- [`chiral_perspective_topdown.png`](chiral_perspective_topdown.png) shows the scene
  in X-Z, including actor/controllers, gaze, structure axis, and endpoint markers.
- [`chiral_perspective_evidence.json`](chiral_perspective_evidence.json) records the
  strict projection checks and their PASS/FAIL result.
- The matching SVG files are the lossless source exports used for rasterization.
- [`hmd_room_grid_live_poc.png`](hmd_room_grid_live_poc.png) is a real composited
  desktop-window capture from the physical left-eye mirror with the six-color
  OpenXR LOCAL-space room cage enabled. It proves the eye framebuffer reached the
  desktop, but not yet that physical headset motion is directionally correct.
- [`hmd_room_grid_spectator_fallback_poc.png`](hmd_room_grid_spectator_fallback_poc.png)
  is a real desktop-window capture after SteamVR suppressed headset submission. It
  proves the labeled fallback continued rendering the located-eye view and its green
  liveness heartbeat; it is not a submitted-eye or compositor capture.
- [`hmd_chiral_origami_submitted_poc.png`](hmd_chiral_origami_submitted_poc.png) is a
  real `SUBMITTED` left-eye capture after SteamVR idle pausing was disabled. The
  asymmetric 3D fixture is centered 1.30 m along the initial HMD gaze, carried into
  the HMD presentation frame, and shown at 2× scale among the room-grid references.

The exporter reads the real natural Full scene primitives and uses the viewer's
normalization and placement plus the Witness script's pose. It is a pose/geometry
diagnostic, not a capture of the live OpenGL stereo path. The retained checked run
fully frames and minimally resolves all 16 primitives, clips none, occupies
`0.024265` of the image bounds, and has `0.000°` gaze error. The older
`simple_origami_*` flat-tile files remain historical POC output, not the canonical
perspective gate.
