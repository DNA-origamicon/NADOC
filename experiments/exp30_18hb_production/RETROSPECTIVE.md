# exp30 — testing/validation retrospective

Ranked suggestions for improving how this run is monitored/validated, from evidence
so far. **[APPLIED]** = done (safe, reversible). **[PROPOSE]** = needs user sign-off
(touches live trajectory / NAMD config / correctness).

## 2026-06-14 (seg 2/12, k=0.5; 3.06 ns/day; first gate C1'=100% WC=94.8%)

1. **Disk headroom — TOP RISK.** 47 GB free on `/` (78% used). Full run ≈ **34 GB of
   DCD** (34 MB/frame × ~1000 frames at dcdFreq 9600) + restart files + resume
   `cont*.dcd` duplication (each resume re-writes its segment's remaining frames to a
   new file). Margin ~13 GB; a crash/relaunch loop could fill it → NAMD write failure
   mid-segment.
   - **[APPLIED]** `monitor_18hb.py` now reports disk-free GB each tick (in the row +
     printed line) so the margin is tracked.
   - **[PROPOSE]** watchdog disk guard: refuse to relaunch and alert loudly if free
     < ~8 GB (prevents a crash-loop from filling the disk).
   - **[PROPOSE]** lower `dcdFreq` for the long p100 segments (1.2 M steps) to halve
     trajectory size — costs frame resolution, your call.
   - Housekeeping: completed-segment `.dcd`/`cont*.dcd` ARE the trajectory — do not
     delete to reclaim space without exporting first.

2. **Monitor stall blind spot.** When the launcher is alive but NAMD silently hangs,
   the verdict stays RUNNING_PROGRESSING forever (it trusts launcher-liveness). Also
   the restart-`.xsc` step lags the live step by up to one restartfreq (~6 min), so a
   freshly-started segment shows a stale step.
   - **[PROPOSE]** also parse the live step from the segment log's last `ENERGY:` line;
     flag STALLED if it hasn't advanced across two checks even with the launcher up.
     Gives finer progress + catches a hung (not dead) NAMD.

3. **Throughput ceiling — offline experiment (no live-run risk).** GPU-resident gave
   2.2× but GPU util stays low → PME-bound on the elongated box (Z≈1382 Å). Possible
   further 1.3–1.5×.
   - **[PROPOSE]** benchmark OFFLINE from a checkpoint (as the CUDASOA test was):
     `+p8`/`+p4` vs `+p16`, and a `PMEGridSpacing` sweep. Pure benchmark, doesn't touch
     the live run; adopt only if clearly faster AND energy-stable.

4. **Health gate as k steps down — WATCH (no change).** k=0.5 passed with huge margin
   (C1'=100%, WC=94.8%). The real test is k=0.1 → 0.01 → 0. Thresholds (C1'≥90,
   WC≥80/75) are right; the k=0 fallback (hand off at last passing k) is the designed
   safety net. exp29 says 18hb (large bundle, no strain, +50 mM salt) is the favorable
   case, so optimism is warranted — but the k=0.1 WC step is where exp29's 6hb first
   wobbled; watch that sample specifically.

5. **GPU-resident is package-local, not durable.** `CUDASOAintegrate on` lives only in
   this run's 12 dynamics confs. A package re-prep would silently revert to 1.4 ns/day.
   - **[PROPOSE]** add `GPUresident on` to the dynamics-conf generator in
     `md_protocols.py` (guarded for GPU runs) so future runs get it by default.

6. **Cadence — OK.** watchdog 10 min + agent 2 h + twice-daily; 0 watchdog failures,
   1 (fixed) resume abort. Catches health-gate failures within ~2 h. No change; could
   trim the 2 h agent cron to save tokens since the watchdog covers mechanical
   resilience, but current coverage is appropriate for an unattended multi-day run.

## 2026-06-15 09:18 (seg p50 ~85%, k=0.5; 3.06 ns/day; 0 watchdog relaunches)

- **Disk projection refined & guard APPLIED.** 44 GB free; 4.9 GB DCD for ~1.05M
  steps → full run ~36 GB steady-state (no resumes) ending ~12 GB margin. Fits IF
  resumes stay rare (each adds a duplicating `cont*.dcd`). **[APPLIED]** watchdog now
  refuses to relaunch and logs `DISK CRITICAL` if free < 8 GB (prevents a crash-loop
  from filling the disk + corrupting a write); watchdog restarted to load it. The
  earlier dcdFreq/PME proposals still stand for the user.
- **Run stability strong:** 0 watchdog relaunches since the resume fix; 1/12 gates
  passed (p10: C1'=100%, WC=94.8%); p50 gate imminent. GPU 100% in steady dynamics —
  the offload-mode low-util worry was transient; GPU-resident is using the card well.
- No change to items 2–6 (2026-06-14). Next signal to watch remains the **k=0.1 WC**
  health sample (exp29's 6hb first wobbled there).

## 2026-06-15 21:17 (p100 ~54%, k=0.5; both k=0.5 gates passed 100%/94.8%; 3 ns/day)

- **Disk margin tighter than projected.** 41 GB free, 8.0 GB DCD for 1.84M steps →
  rate 4.34 GB/M-step (higher than the frame-size estimate; the one p10 resume's
  `cont1.dcd` duplication inflated it). Full run ≈ **42 GB DCD → ~7 GB end margin**
  (vs ~12 GB last estimate). Still fits a clean run. The 8 GB watchdog guard is
  correct but, by design, may pause an auto-resume in the final segment (where free
  ≈ 7–8 GB) — that's the safe failure (alerts the agent rather than filling disk).
  - **[PROPOSE]** halve `dcdFreq` (9600→19200) on the not-yet-run k=0.1/0.01/0 segment
    confs to reclaim ~half the remaining ~34 GB — config edit, your call.
- **Source tree has unresolved merge markers** (`namd_topology.py` + its test) from a
  two-computer sync that popped my stashed segid fix against your upstream
  `_psfgen_segid` (D000). **Does not affect the live run or resilience** (verified:
  `--resume` + monitor import clean; my resume fix survived), but **`just test` is red
  and re-prep would fail** until resolved. Validation-process note: the upstream test
  encoded a different segid expectation than my stashed tests — the suites must be
  reconciled when you finish the merge. Clean fix = take upstream `_psfgen_segid` for
  both files (awaiting your go-ahead; I'm not touching your in-flight merge).
- Health margin huge at k=0.5; **k=0.1 is the next real test** (exp29's 6hb first
  wobbled there). No threshold change. Throughput/PME items unchanged from 06-14.
