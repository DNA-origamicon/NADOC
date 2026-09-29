# VR blur increase and master synchronization — 2026-09-28

Increased the blur sampling radius from 10 to 15 pixels (+50%), retaining the
10% white / 90% scene composite and faint button styling. The independent image
oracle's Gaussian width increases proportionally (7 to 10.5 pixels); its pass
thresholds remain unchanged. Native telemetry reports `blur_radius_px: 15`.

`git pull --no-rebase origin master` reported already up to date. The previously
approved `feature/standalone-viewer-presentations` branch had one newer commit,
`18d287a7` (smooth trajectory playback and frame preparation). It merged cleanly
into master as `092aa89d`, without conflicts. Regenerated the desktop-to-VR sidebar
catalog for its new interpolation controls; VR simulation trajectories remain
excluded by the existing filter.

The task commit includes this session's VR simulations, frosted menus, calibrated
floor, demos, tests and documentation. Unrelated dirty research/solver files are
excluded. No stash, reset, history rewrite or force push was used. Frontend
`main.js` change for the simulation integration is +7/-3, net **+4 wiring lines**.
The blur adjustment itself changes no frontend main entrypoint lines.

Evidence: `.development-artifacts/vr-blur-50/`.

- All four controller motion profiles pass the stereo blur/text, calibrated-floor
  and actual desktop-mirror checks with the new 15-pixel blur radius.
- Merged frontend suite: 569 files; 7,242 tests passed, one skipped.
- Generated sidebar catalog freshness check and scoped Python Ruff checks pass.
- Worn-headset comfort remains a manual review item. The known CanDo small-design
  expansion bug remains deferred; no saved simulation coordinates were altered.
- Final native rebuild and five focused native tests pass.
- The first backend run exposed a pixel-oracle regression for muted disabled
  scrollbar thumbs. Restored the existing 50-level minimum for disabled thumbs;
  blank tracks still fail. All four focused pixel-oracle tests pass.
- Final backend fast suite: **9,402 passed, 93 skipped, one failure** in the
  pre-existing `test_the_scalar_and_loop_skip_fast_paths_agree` exact-array
  comparison. This also failed before the VR changes; geometry is unchanged.
- Fingerprints confirm all 46 unrelated tracked dirty files were preserved.

```text
decision: FAST  (fast suite only)
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```
