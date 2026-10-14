# CPD resume handoff — 9 October 2026

**Historical pause, superseded by subsequent explicit user resume on 2026-10-09.**
See current campaign entry and v15 continuation; retain this checkpoint record.

Anti3 worker and completion watcher were stopped, watcher first. Both are
inactive/dead; no NAMD process remains. A delayed wake must not restart jobs.
Original supervisor status may still say running; pause receipt and systemd
state supersede it. No commit requested for this pause.

Archive root: `/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/cpd-anti-gpu-cube-context-v5`.
Pause receipt: `campaign_pause_20261009.json`, also copied to
`cpd-anti-cube-validation-anti-3-service-v6/user_pause_20261009.json`.

## Verified restart

Anti replica3: nine1ns segments passed worker checks; independent full replica
audit pending. Segment10 interrupted. Latest complete checkpoint step5050000,
validation9.04ns, prefix `anti/replica-3/validation/segment-10/checkpoint.5050000`.
Coordinate/velocity arrays finite for265477atoms; fullXSC step/cell match DCD;
chemistry/water/image gates pass. Receipt pins coor/vel/XSC hashes.
Last logged step5073000 is uncheckpointed tail and must not be credited.
Remaining480000steps at2fs =0.96ns to5530000 (10ns validation).

## On explicit resume

1. Verify archive, no competing NAMD or stale watcher, and checkpoint hashes.
2. Audit completed9ns and partialsegment10 through5050000; preserve all raw
   outputs. Interrupted log lacks normal termination. Compare restart potential
   to ENERGY at5050000, not the final log row.
3. Create uniquely named continuation output,plan,authorization and deadline.
   Restore coor,vel,fullXSC; firsttimestep5050000; declare fresh RNG seed without
   promising bitwise Langevin continuity. Keep p4,2fs ordinary masses,NPT,
   PME144cube,force-switch10–12A,100ps restart triples,10ps DCD.
   Recheck performance: recent~55min/ns supports a2h cap for0.96ns plus checks.
   Never revive old deadline or rerun the original existing validation directory.
   Adapt v13control2 wrapper to anti3 in a new version; it is hardcoded and must
   not be run unchanged. CPU/native checkpoint-energy checks precede dynamics.
4. Arm a new watcher for the current thread. Old watcher token
   `4e06a1c3-608f-4ada-b44a-49942b118ca2` stays stopped.
5. Aggregate900 completed frames,4 partial frames and96 continuation frames,
   exactly1000 distinct10ps frames. Full native/cell/checkpoint audit and
   physical/structural/performance review before admitting control3.
6. Finish control3 sequentially, then all-six matched interpretation,provenance
   errata and restartable package. No cloud spending or readiness promotion.

Four of six10ns runs fully audited (anti1,control1,anti2,control2). Anti3 remains
incomplete. Shared28contact ordering reverses between the first two pairs,
with different prepared baselines; retain all results without selective refit
or extension. Anti2 startup bad_any_cast failure remains preserved and unresolved;
recurrence requires investigation,not automatic retry. Simulation readiness,
minimum certification and equilibrium claims remain false.
