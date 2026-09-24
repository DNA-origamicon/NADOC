# Independent volume coloring and hull openings

ViewVolume now persists `coloring` with a backward-compatible strand default.
Choices use the shared representation/color-support table. Changing representation
falls back only when the current local scheme is unsupported. Creation copies the
current supported global scheme; subsequent global coloring changes leave it alone.

Independent volume displays own separate CG/atomistic/surface renderer instances.
Atomistic renderers retain shared preferences by default, with an explicit isolated
color state for volumes. This preserves existing simulation behavior. The native
CG column channel yields within every volume; local layers stay visible even when
Hull Prism hides native CG. Coarse LOD membership uses current geometry if no
backbone instances exist. Opacity, colors and overlapping layers are independent.

Hull openings use a trusted shader patch: camera rays intersect rotated boxes or
hexagonal prisms and discard hull fragments in that projected footprint. A simple
spatial fragment mask is insufficient for a fully enclosed volume; this aperture
reveals its contents from either side. Local-coordinate masks stay attached during
multi-overlay separation. Disabling a volume restores the hull. Molecular/topology
coordinates remain unchanged. Prepared packages validate and restore this patch
(v6); old hosts are rejected via `hull-cutouts-v1`. Display fingerprints include
mask changes even when volume outlines are hidden.

Multi-overlay initializes layer 1 from the active global representation on entry;
remaining layers default to cylinders. Explicit programmatic choices are retained.

Validation:
- Final focused unit run: 123 passed, including volume picking across independent
  atom/surface/CG layers. Lint and production build pass.
- Final `just smoke`: 23 passed. Test workspace files/history, browser artifacts,
  and isolated bridge credentials cleaned up. Concurrent browser/smoke reporters
  briefly raced on artifact removal; final cleanup verified after both finished.
- Combined browser regression: 3 passed (new volume controls/pixel test plus
  existing representation-sharing exercise).
- Browser exercise: local base coloring survives global cluster coloring; volume
  enable/disable controls hull masks; version-6 export works; entering from oxDNA
  yields oxDNA/cylinders/cylinders.
- Pixel regression: an opaque green hull fully encloses a red object. Its center
  pixel becomes red through the active aperture, and the shared round trip matches.
  Disable/re-enable with a moved aperture is covered to catch stale cached uniforms.
- View-volume API/persistence tests: 2 passed.
- Full frontend run: 6,867 passed, 1 skipped; unrelated quantum-dot image import
  failure plus a PEG live-controller timing failure. PEG passes in focused rerun.
- `just test-smart`: FAST; 8,855 passed, 7 skipped, 7 failed in the unrelated
  photoproduct-review tests. Guard time 116 s exceeds aggregate 90 s; no per-test
  violators (slowest 4.39 s). Triage follows `.claude/skills/triage-slow-tests/SKILL.md`:
  consistent with the previously documented 116 s aggregate run in
  `memory/project_test_parallelization.md`, so no tests were moved or limits changed.

Deferred output from the backend guard:

```
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

`main.js` LOC delta: 0. Large-design translucent appearance and remote-device
validation remain tracked under MV-REPRESENTATION-SHARING. Each independent CG
volume currently builds its own renderer; large designs with many volumes require
performance validation. Hull masks support up to 64 simultaneously enabled volumes.
