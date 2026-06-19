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

## 2026-06-16 09:17 (k=0.1 p50; 4/12 gates passed; 3 ns/day; 0 relaunches)

- **Health curve validates the favorable-case prediction.** All 4 gates passed:
  k0.5 p10/p50/p100 = 100/94.8, 100/94.8, 100/95.2; **k0.1 p10 = 99.8/88.9**. C1'
  pinned ~100%; WC declines gently (95→89) as k relaxes — no sign of the exp29 6hb
  k=0.1 WC wobble (which cratered ~75%). The large bundle + 50 mM salt + no strain is
  doing exactly what exp29 Cycle 5 predicted. **The remaining real test is k=0** (the
  true-zero melt); the k=0 fallback (hand off at last passing k) stays armed.
- **Disk margin ~6 GB at completion (tightening, still fits a clean run).** 37 GB free,
  12 GB DCD for ~2.64M steps (4.5 GB/M-step) → ~43 GB total → end ~6 GB. The 8 GB
  watchdog guard only blocks crash-resume (not normal writing), so a clean run finishes
  fine; a crash in the final k=0 segments (free <8 GB) would need manual intervention.
  - **[PROPOSE, rising priority]** halve `dcdFreq` (9600→19200) on the not-yet-run
    k=0.01/0 confs → end margin ~14 GB instead of ~6. Config edit to your output
    resolution, so your call.
- ETA ~4.6 days (≈ Jun 21) for the remaining 8 segments at 3 ns/day.
- Merge markers in `namd_topology.py`+test still unresolved (no run/resilience impact;
  `just test` red). Awaiting your go-ahead to take upstream `_psfgen_segid`.
- No clearly-safe code change to apply this tick; remaining items are config/merge
  (propose-only) and the optional offline PME/PE benchmark (lower priority now).

## 2026-06-16 21:17 (k=0.1 p50 ~93%; 4/4 gates passing; 3 ns/day; 0 events)

- **Event-free 24h+ on the long k=0.1 segments** — 0 relaunches, 0 disk-criticals, no
  false alarms. Cadence (watchdog 10 min + agent 2 h + twice-daily) is well-matched:
  nothing missed, no noise. No change warranted.
- **Disk projection holding:** 34 GB free, 6.07M steps remaining × 4.5 GB/M → ~27 GB
  more → **~7 GB end margin**. Stable vs prior estimate. dcdFreq-halving [PROPOSE]
  still stands; not urgent unless a crash-loop erodes the margin (guard covers that).
- **xsc signal confirmed pinned for the whole k=0.1 stage** (sub-segment counters
  0→960k never exceed the k=0.5 p100 final 1.2M). Harmless to the watchdog (false
  stalls need a dead launcher, where relaunch is wanted anyway); I verify live step
  from the log when xsc is flat. The [PROPOSE] log-step parse would remove the manual
  step but isn't safety-critical — holding it to avoid editing the single-point monitor.
- No new safe code change. Open user items unchanged: dcdFreq (disk), merge-marker
  resolution (`just test` red), optional offline PME/PE benchmark.

## 2026-06-17 09:17 (k=0.1 p100 ~63%; 5/5 gates passed; 3 ns/day; 0 events)

- **5/5 gates passed**, curve still pristine: C1' 99.8–100% throughout; WC 95→88 and
  flat across k=0.1 (88.9→88.3) — fully stable, no decay trend. k=0.1 nearly done.
- **Disk ~6 GB end-margin, now the firm watch item.** 30 GB free; ~5.24M steps left ×
  4.5 GB/M ≈ 24 GB more. Clean run fits; guard covers a crash-loop. dcdFreq-halving
  [PROPOSE] is the lever if you want comfort — config edit, your call (I won't act).
- **ETA ~3.5 days (≈ Jun 20–21).** Remaining: k=0.1 p100, k=0.01 ×3, then **k=0 ×3 —
  the real test** (true-zero melt). k=0 fallback (hand off at last passing k) armed.
- No new safe change; open items unchanged (dcdFreq, merge resolution, optional PME
  benchmark).

## 2026-06-17 21:52 (k=0.01 p10; 6/6 gates passed; 3.0–3.6 ns/day; 0 events)

- **k=0.1 complete, all 6 gates passed.** Curve flat/strong: C1' 99.7–100%, WC plateaued
  ~88 across all of k=0.1 (no decay). Now in k=0.01 (final ENM stage before true zero).
  Throughput ticked up to ~3.6 ns/day under the weaker k=0.01 restraint.
- **Disk ~7 GB end-margin holding** (28 GB free, ~21 GB to go). Stable. dcdFreq [PROPOSE]
  unchanged.
- **k=0 (3 segments) is the decisive test** and is ~2 days out (ETA ≈ Jun 20). If C1'
  holds ≥90 through k=0 → full production success; if it melts, the armed fallback
  records the last passing k (k=0.01) and writes REPORT.md — no silent fail.
- No new safe change; open items unchanged (dcdFreq, merge resolution, optional PME bench).

## 2026-06-18 09:17 (k=0.01 p50; 7/7 gates passed; 3.5 ns/day; 0 events)

- **WC trend now informative for the k=0 prediction.** WC ref-relative steps down as
  restraint weakens: k0.5 ~95 → k0.1 ~88 → **k0.01 p10 = 83.2** (C1' steady 99.7%).
  Extrapolating, k=0 (no ENM at all) WC may land ~78–80 — *near but above* the relaxed
  **k=0 WC threshold of 75%** (vs 80% under ENM). C1' (primary, ≥90) is rock-solid and
  should pass k=0 comfortably; WC will be the closer gate but is designed to relax there.
  This is the favorable outcome exp29 predicted for a large salted bundle.
- **Disk margin improved to ~8–10 GB** (26 GB free, ~3.5M steps left × 4.5 GB/M ≈ 16 GB).
  Comfortable now; dcdFreq [PROPOSE] effectively moot for the remainder.
- **ETA ~2 days (≈ Jun 20 eve).** Remaining: k0.01 p50/p100 + k=0 ×3 (the melt test).
- 0 relaunches/disk-criticals across 4 days; resilience + cadence validated end-to-end.
  No new safe change; open items unchanged (merge resolution for `just test`; optional
  PME bench).

## 2026-06-18 21:17 (k=0.01 p100, last restrained stage; 8/8 gates; 0 events)

- **Biggest finding to date — stage durations ~5–10× over-provisioned** (see ANALYSIS.md,
  written today for the user's Q1/Q2). Within-segment energy/volume/base-pairing/global-Rg
  all plateau by the 10% checkpoint (~0.5 ns of 4.8); the only macroscopic work is the
  first post-min NPT segment (box −7.5%). Useful change lives at the discrete k-steps, not
  the holds. **[PROPOSE] for the NEXT run:** compress the restrained ladder (e.g. ~0.5–1 ns
  per k) and reallocate the saved ~10–12 days of GPU time to a long k=0 production, where
  the slow modes finally sample. Do NOT alter the current run's remaining confs — let it
  finish as the clean reference.
- **k=0 is both the decisive melt test AND the high-value ML-surrogate transition**
  (k0.01→0 is where slow modes move; the restrained transitions are near-identity / low
  info). [PROPOSE] add per-nucleotide CG logging before k=0 so this run captures that
  transition richly (offered to user; awaiting go-ahead).
- Safety: 8/8 gates passed, C1' 99.7–100%, WC 95→82 (gentle, threshold-relaxes to 75 at
  k=0). 0 relaunches/disk-criticals over 5 days; disk ~8 GB end-margin holding.
- Open user items: merge-marker resolution (`just test` red); CG-logging + ladder-compression
  decisions above. No new clearly-safe code change this tick.

## 2026-06-19 09:17 (k=0 p50; 10/10 gates incl. first true-zero; DECISIVE TEST SURVIVED)

- **18hb survives true k=0 — full production success in sight.** First unrestrained gate
  (no ENM): **C1'=99.4%, WC=77.9%**, both above the relaxed k=0 thresholds (90/75). C1'
  barely moved across the whole ladder (100→99.4); the melt that killed 2hb/6hb in exp29
  did NOT occur for the large salted 18hb bundle — exactly the favorable-case prediction.
- **Monitoring approach validated predictively:** the 06-18 WC-trend extrapolation
  (95→88→83→82 → "~78–80 at k=0, above 75") landed at 77.9. The sparse 3-gate/stage
  sampling + trend tracking was sufficient to anticipate the outcome — no finer health
  cadence needed.
- **2 segments left (k=0 p50, p100); ETA ~1 day.** Disk ~10 GB end-margin (18 GB free,
  ~8 GB to go) — clears the 8 GB guard. 0 relaunches/disk-criticals over 5+ days.
- On COMPLETED: write REPORT.md (full health curve + the k=0 survival) and CronDelete both
  crons. No new safe code change. Open user items unchanged (merge resolution; next-run
  ladder-compression + CG-logging from ANALYSIS.md).
