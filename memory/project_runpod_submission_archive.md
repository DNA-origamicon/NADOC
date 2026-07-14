# project_runpod_submission — ARCHIVE

History and the full narrative of each bug. **Never read this in a routine loop.**
The durable protocol is [REFERENCE_RUNPOD_RUNBOOK](REFERENCE_RUNPOD_RUNBOOK.md); the
symptom index is [LESSONS](LESSONS.md) category **L**. Open this only to mine a
specific past decision.

---

## FOUR bugs the live run found — each cost a real, billing pod

1. **`gpuTypeIds` must be arch-filtered.** `build_patched_namd.sh` compiles for ONE
   `sm_XX` ("single arch: ~4x faster nvcc pass") and the volume's build is **sm_89**. When
   no 4090 was free, the fallback rented an **A100 (sm_80)** — which booted fine and then
   died at step 0 with `cudaMemcpyToSymbol ... bindExclusions ... no kernel image is
   available`, the SAME failure as the local sm_75 binary on the 4090. `GPU_TYPES` now
   carries an `sm` field and `NAMD_BUILD_ARCHS = ("sm_89",)` filters it. **To use A100/
   A6000/H100, rebuild NAMD multi-arch and widen that tuple.**
2. **A price ceiling is mandatory.** Unbounded "fall back to whatever is available" rented
   a **$1.39/hr A100** to relax a 225k-atom duplex whose cheapest viable card is $0.34.
   `DEFAULT_MAX_USD_PER_HOUR = 1.00`.
3. **`+p` needs a CAP, not just a halving.** The A100 host had 128 vCPUs → `vcpus//2` asked
   for **`+p64`**, far off the end of NAMD's single-GPU scaling curve. `MAX_NAMD_THREADS = 16`.
4. **Never set `dockerStartCmd`.** It REPLACES RunPod's own start script — which is what
   launches **sshd**. A pod created with `sleep infinity` boots, reports RUNNING, exposes
   port 22, and refuses every SSH connection.

Plus two that cost only time:
- **`cd D && CMD &` re-subshells the launch** and that subshell's stdout is still the SSH
  channel, so the channel never closes and `conn.run` times out. Use `;`, so `&` binds to
  the redirected `setsid` alone.
- **`!NATOM` is NOT in the first 4 KB of a PSF.** psfgen writes one `REMARKS` line per
  patch: 6hb has 604 title lines (`!NATOM` at byte 18,729), flat_1x50 has **7,342** and it
  lands past 64 KB. Stream lines; never head-read.

## OLD — superseded (kept for the reasoning)

Everything above is built and tested, but **the Run button does not yet dispatch to
RunPod**. To close the loop:

1. `routes_md.start_md_job` (and the create/autostart path) must branch on
   `execution_target == "runpod"` → `runpod_executor.run_job_on_pod(...)`, taking the
   API key + `network_volume_id` from `routes_runpod._SESSION`.
2. A supervisor poll loop for runpod jobs (mirror `md_executor.poll_remote_jobs`, which
   filters `!= "alpine"` and therefore skips them).
3. `n_atoms` for sizing: read `!NATOM` from the package PSF (`routes_md` already does this
   for the production disk estimate).
4. `min_name`: from `manifest.json["minimization"]["name"]`.
5. **NOT YET EXERCISED IN THE APP** — the radio is served and the pure logic is unit-tested,
   but no click-through and no live pod round-trip. Phase 4 = end-to-end on a real pod.

- [x] **Phase 5 — a REAL production-scale ladder (3x6x400, 1.94M atoms).** 2026-07-14.
      The 6hb e2e (Phase 4) proved the *plumbing*; it did not exercise a single one of the
      things that actually break at scale. Five bugs, four of them SILENT:
      1. `early_stop_relax` was a no-op on runpod (the flag existed, nothing read it).
      2. Tier B structurally cannot pay for a real ladder (can't touch k < 0.1).
      3. `fast=True` silently disabled early-stop via the frame budget (4x cost).
      4. `cell_shrink` retry could never heal (restarted from the ORIGINAL box).
      5. `GPU_TYPES` held COMMUNITY prices in a SECURE-only world (~2.2x under).
      Plus: production child didn't inherit `archive_path` (trajectory → system disk),
      the $15 was a per-JOB cap not a session cap, and PEP 668 blocks `pip install`.

- [ ] **Phase 6 — the panel.** Cost readout, pod-leak reaper on startup, and the Clusters
      card / RunPod radio / pre-flight gate have STILL never been clicked in a browser.
      Everything above was driven from `experiments/exp43_runpod_bench/*.py`.

## MEASURED on a rented RTX 4090 (2026-07-13) — the numbers the code is calibrated to

32 vCPU / **16 physical cores** / 131 GB RAM / 24,564 MB VRAM, NAMD 3.0.2p1 (patched),
$0.34/hr community cloud.

| system | atoms | conservative 2 fs | fast HMR+4 fs | **fast + GPU-resident** | offload VRAM | resident VRAM |
|---|---|---|---|---|---|---|
| 6hb_sim_v2 | 225,504 | 20.73 | 41.38 | **137.49** ns/day | 854 MB | 1,114 MB |
| flat_1x50 | 1,442,735 | 2.59 | 5.15 | **21.29** ns/day | 3,496 MB | 5,016 MB |
| VoltronCore | 5,656,632 | cell_shrink | cell_shrink | **4.48** ns/day | 12,334 MB | **17,678 MB** |

- **GPU-resident is worth 3.3–4.1×** and scales BETTER with system size. NADOC's shipped
  `equilibrium_aware` confs do NOT enable it (only the `fast` path does) — that is the
  single biggest free win, locally and remotely.
- **A 5.66M-atom system fits GPU-resident in 24 GB** (17.7 GB). VRAM model:
  `offload ≈ 2100 MB/Matom + 400`, `resident ≈ 3212 MB/Matom + 400` — predicted 18,571 MB
  for VoltronCore vs 17,678 measured (5% conservative, the safe direction).
- **`+p` must equal PHYSICAL cores.** `+p32` on 16 real cores ran 18.85 ns/day vs `+p16`'s
  41.38 — oversubscribing SMT **halved** throughput. RunPod advertises vCPUs → `vcpus // 2`.
- The extreme flat box (1146 × 44 × 294 Å, 26:1) is a **non-issue** — minimised clean, no
  patch-grid trouble. Box anisotropy was not the problem it was assumed to be.

## Traps that cost hours — encoded as code + tests, do not re-derive

- **NAMD renames its process to `NAMD masterPe`.** `pgrep -x namd3` matches NOTHING and
  reports a live job as dead. A CPU-only control run therefore survived `pkill`, ate 32
  threads for an hour, and silently contaminated an entire benchmark (every ns/day ~6× low,
  GPU at 4%, and it produced the FALSE conclusion "GPU-resident gives no speedup"). **Track
  the PID you spawned; match `argv[0]`, never the process name.** Both the chain script and
  the bench harness now refuse to run on a contended machine.
- **A NaN-stalled minimisation never exits.** Its line minimiser sits on NaN forever. Needs
  the stall watchdog (no log output for N minutes → kill), or a wedged job bills until the
  account is empty.
- **The watchdog subshell must have its stdio detached** (`) >/dev/null 2>&1 &`). Otherwise
  its orphaned `sleep` holds the script's stdout pipe open after NAMD exits and every reader
  blocks a full poll interval per step — the job looks hung. Load-bearing, not tidiness.
- **`cell_shrink` is a RESTART, not a failure.** An NPT box relaxing ~3% to equilibrium
  density crosses NAMD's fixed patch grid → "Periodic cell has become too small". It killed
  BOTH offload VoltronCore cells. Self-healing on restart; bounded retry in the chain script.
  **Never "fix" it with a `margin` keyword** — that crashes the GPU tile-list kernel on a
  carved box.
- **NAMD reports throughput in DIFFERENT UNITS by mode**: offload prints `days/ns`,
  GPU-resident prints `ns/day`. Parsing one silently drops every cell of the other.
- **`GPUresident` must precede `run`** in a conf. After `run` it is a runtime change to an
  already-finished simulation: NAMD dies with "Can't modify CUDASOAintegrate when that mode
  was never enabled" — *after* silently running the whole segment in offload mode.

## Relaxation early-stop on a pod (2026-07-14) — the feature that makes a big ladder affordable

**`early_stop_relax` existed for `local` and `alpine` but NOT `runpod`.** The flag was
settable on the job and `render_chain_script` **silently ignored it** — no code path read
it. That is not a missing nicety, it is the difference between a run happening and not:
the 3x6x400 ladder is 4.8M steps (at 4 fs) ≈ **28 h ≈ $21** un-accelerated, which fits
neither a night nor a budget.

Ported by **reusing `slurm_script`'s emitters** (`_early_stop_block` / `_bridge_lines`)
rather than copying them — the bridge bash is the subtle half (explicit names, never a
glob, so `_p50` can't sweep `_p100`) and a second copy would drift out of lockstep with
the tests that pin it.

**The bridge and the resume trick are the SAME trick.** On a plateau the pod copies the
chunk's final `{coor,vel,xsc}` onto every remaining chunk's expected names; `run_step`'s
existing "`output/<name>.coor` exists → SKIP" guard then walks straight past them, and
the next stage's `previous` (which points at `_p100`) finds the bridged file. No new skip
logic was needed.

⚠️ **Tier B CANNOT pay for a real ladder.** Tier B (stdlib, energy+volume plateau) may only
skip stages restrained at ENM `k >= 0.1` — below that, base-pairing keeps degrading after
the energy flattens, so an energy-only plateau would bridge away a stage that hadn't
finished relaxing. **k=0.01 and the k=0/MGHH melt therefore always run in FULL**, capping
Tier B at ~5.28M of the 9.6M 2-fs steps — over budget in its BEST case. **Tier A** (WC
base-pairing gate, needs MDAnalysis on the pod) holds the fragile stages directly and makes
EVERY chunk eligible; that is where exp36's measured **4.9×** comes from.

⚠️ **Tier A fails SAFE to HOLD, and "hold" on a rented pod is a BUDGET event.** No
`wc.json` (MDAnalysis missing, health step failed) → no skip → the full expensive ladder,
until the kill-switch guillotines it half-finished — neither a finished relaxation nor the
money to retry. So `runpod_executor._ensure_mdanalysis()` is a **hard gate**: a pod that
cannot import MDAnalysis refuses to launch. (The pytorch image ships numpy+scipy but not
MDAnalysis; it is a ~30 s pip.)

## ⚠️ GPU_TYPES carried COMMUNITY prices — every estimate was ~2.2× low (fixed 2026-07-14)

Community cloud is **excluded in code** (no card in EU-RO-1, where the volume pins us), so
the only prices we can pay are SECURE — and the table held the community ones. Live-checked
against RunPod's `gpuTypes` GraphQL:

| card | community | **SECURE (what we pay)** |
|---|---|---|
| RTX 4090 | 0.34 | **0.69** |
| RTX PRO 4500 | 0.34 | **0.74** |
| RTX 6000 Ada | 0.74 | **0.77** |
| RTX PRO 5000 | 0.82 | **0.96** |

`plan_execution` and `POST /runpod/estimate` both read these, so both were lying — a "$5"
overnight ladder is really $11. **The live kill-switch was never affected**
(`lifetime_for_budget` uses the pod's *actual* reported rate).

The table is **strictly cheapest-first** again (pinned). The PRO 4500 had been put first
only because at the community price the two **tied** at $0.34, making its 32 GB + HIGH
stock a free tiebreak; real prices break the tie. Leading with the cheaper-but-scarce 4090
costs nothing — `gpuTypeIds` is a **fallback list**, so RunPod just rents the next card
when none is free. (Which is exactly what happened on the first real run: asked for a 4090,
got a PRO 4500 at $0.74.)

## ⚠️ `fast=True` SILENTLY DISABLED early-stop — a 4× cost bug with no error (fixed 2026-07-14)

The nastiest bug of the night, and it produced **no failure of any kind** — the accelerator
was emitted, ran, and answered. It just answered **HOLD every single time**.

`outputEnergies`/`dcdFreq` were a hardcoded **9600 STEPS**. Chunk step-counts are derived
from a target simulated *TIME*, so enabling `fast` (2 fs → 4 fs) HALVES every chunk's step
count for identical physics — while a step-denominated print interval keeps firing just as
often *per step*, i.e. **half as often per nanosecond**. A p10 chunk fell from **25 ENERGY
frames to 12**, under the evaluator's `min_frames = 20`. `energy_plateaued` therefore
returned False for every p10 in the ladder, **no p10 could ever bridge**, and the
accelerator's ceiling collapsed from ~4.9× to ~2×.

On the live pod that turned a **~4 h / ~$3** ladder into a **~15 h / ~$11** one that could
not finish inside its own kill-switch. Caught only by reading the evaluator's `min_frames`
against the conf's actual cadence — never by a failure.

`md_protocols._output_freq(steps)` now derives the cadence from the chunk's own length
(~30 frames), so the frame count is **invariant under the timestep** — the only thing the
evaluator cares about. `tests/test_md_cutoff.py::TestEarlyStopFrameBudget` pins it and is
proven can-go-red.

**The general lesson: any step-denominated cadence is a latent bug the moment the timestep
becomes a variable.** `_display_dcd_freq` had the same shape (it *took* `steps` and ignored
it). Check `restartfreq`/`xstFreq` consumers before trusting them either.

Related, NOT fixed (needs a physics call): **`fast` also halves the SOFT first chunk's
step count while its timestep stays 1 fs** (`timestep = 1.0 if spec.soft else (4.0 if fast
else 2.0)`), so the soft warm-up drops from 240 ps to **120 ps** of simulated time. It errs
toward *less* warm-up. Harmless-looking, but it is a silent change to protocol intent.

## ⚠️ `cell_shrink` was NOT self-healing on a pod — "bounded retry" meant "fails 4×" (fixed 2026-07-14)

The memory said *"self-healing on restart; bounded retry in the chain script"*. The first
half was an assumption, and it was **false on RunPod**. This path had never been exercised.

Self-healing requires the restart to rebuild the patch grid at the **SMALLER** box. The
chain script's retry simply **re-ran the original conf** — whose `extendedSystem` points at
the *previous* segment's `.xsc`, i.e. the **ORIGINAL** cell. So NAMD rebuilt the same grid,
the box shrank into the same wall, and all four retries died at the identical step.

Measured live on the 3x6x400 pod (the soft chunk shrank at step 4000):

    conf (original) : 156.636 x  89.136 x 1436.190
    restart @ 4000  : 151.972 x  86.482 x 1393.426     (-3.0% on EVERY axis)

`backend/core/remote_resume_conf.py` is the pod-side writer (stdlib-only, vendored,
drop-list pinned in lockstep with `md_protocols._RESUME_DROP`) — the RunPod equivalent of
the local runner's `_write_resume_conf`. On a retry the chain script rebuilds the conf
against the segment's **own** `restart.{coor,vel,xsc}` and runs only the remaining steps.
**Confirmed firing on a live pod**: `SHRINK → [nadoc-resume] resumes at step 4000 → RESUME
… (attempt 1) → START`, then the chunk ran past the point it had died at twice.

⚠️ It deliberately keeps writing the **SAME** `.dcd` (not `md_protocols`'
`.cont<k>.dcd`): Tier-A reads its WC series off `output/<seg>.dcd`, so a continuation
written elsewhere would leave that series holding only the few PRE-shrink frames, fall
under the evaluator's window, and **silently report HOLD forever** — the segment would lose
its ability to bridge, and nothing would say so.

**The meta-lesson, twice over tonight: a documented "self-healing"/"fail-safe" behaviour is
worthless until something has actually watched it heal.** Both this and the `fast`/early-stop
bug presented as *silence*, not as errors.

## ⚠️ A DNS blip ORPHANED a billing pod — and nothing had persisted its id (fixed 2026-07-14)

A routine status poll hit `[Errno -3] Temporary failure in name resolution`. `_request`
turned that transient blip into a **fatal** `RunpodError`; it propagated out of the poll
loop and killed the launcher — and the launcher's `finally` is the **only** thing that
destroys the pod. (The on-pod kill-switch has no API key: it can stop NAMD, never the
billing.) NAMD, being `setsid`-detached with output on the network volume, carried on
perfectly happily — so the ladder kept advancing while nothing on the machine was left to
turn the meter off.

**And it was worse:** `runpod_executor` **never called `job.save()`**. Nothing about the
pod was persisted, so a crashed launcher left an orphaned, billing pod that no later
process could even **name**, let alone reap or resume.

Three fixes: `_request` retries the network layer + 5xx/429 with backoff (never a 4xx — it
fails identically forever and just burns pod-time); the pod id is saved the INSTANT it
exists; and `experiments/exp43_runpod_bench/supervise.py` re-attaches to an orphaned pod
(poll → fetch → destroy). `reap.py --kill` is the panic button — reads `~/.runpod_key`, so
it works with no environment.

## ⚠️ The spend ledger FROZE while a real GPU billed on (fixed 2026-07-14)

The ledger exists **because** the in-code kill-switch is per-POD and has no memory — and
then it grew the same class of hole. A pod bills continuously from creation to destruction
regardless of how many processes watch it. The launcher opened the pod, died (its `finally`
**closed** the row), and a supervisor re-adopted it (a second, **open** row for the SAME
pod). `_all_rows` deduped by keeping the FIRST row — the closed one — so the live row was
discarded and `spent()` **froze at $0.95** while the GPU billed on for another 25 min. The
budget guard reads that number; it could never have fired. True spend was **$1.35**.

Now collapsed per pod: `started` = earliest sighting, `ended = None` if ANY observer still
has it open; and `close_pod()` closes the pod in EVERY job's file.

**A ledger that under-reports is worse than no ledger, because it is trusted.**

## Cost anatomy of the 3x6x400 ladder (1.94M atoms, RTX PRO 4500, measured)

| chunk | timestep | mode | ms/step | note |
|---|---|---|---|---|
| minimisation (4800) | 2 fs | offload | **53.6** | ~5 min; TOTAL → −9.0e6, clean |
| stage-1 p10 (120k) | **1 fs** | **offload** (soft) | **43–51** | **~1.5 h / $1.1** — the most expensive chunk per ns, and unavoidable |
| every other chunk | 4 fs | **GPU-resident** | **26.4** | **13.1 ns/day** at 1.94M atoms |

⚠️ **The RTX PRO 4500 Blackwell is 1.26× SLOWER than the 4090 extrapolation.** The
measured 11.2 ms/step/Matom (4090) predicted **20.9** ms/step; the Blackwell does **26.4**.
The per-Matom fit does NOT transfer across architectures — re-measure on any new card
before costing a run off it.

The soft first chunk is ~40% of a best-case ladder's cost. It is the price of a safe start.

## Tier-A early-stop CONFIRMED on a live 1.94M-atom pod (2026-07-14)

    [nadoc-health] wrote 30 wc frames
    [nadoc-cutoff] {"n_energy_frames": 21, "n_wc_frames": 30,
                    "energy_plateaued": true, "wc_plateaued": true, "tier": "A"}
    [NADOC] early-stop: ..._k0p5_p10 plateaued — bridging 2 chunk(s)
    SKIP  ..._k0p5_p50  (already complete)
    SKIP  ..._k0p5_p100 (already complete)

Stage 1 bridged away **1,080,000 steps**. WC series it judged on: `1.0 → 0.954 → … →
0.949`, flat at ~94.7%.

⚠️ **`n_energy_frames: 21` against `min_frames = 20` — a margin of ONE frame.** Before the
frame-budget fix that number was **12**. And note the *resumed* chunk runs
`total − restart_step`, so a cell-shrink at a LATER step leaves fewer frames: a shrink past
~step 40k would drop a p10 back under 20 and **silently disable its bridge**. Not yet
hardened — `_output_freq` should be derived from the REMAINING steps on a resume, not the
original total.

## ⚠️ You pay GPU rates to DOWNLOAD your results

The network volume is only reachable **through a live pod**, so `fetch_outputs` runs while
the GPU is still billing. The 3x6x400 relaxation produced **5.2 GB** of output; at domestic
downlink (~50 MB/min) that is **~100 min of pod time ≈ $1.20** — a quarter of what the
science itself cost ($3.99), spent moving files with the GPU idle.

Ideas, none implemented:
* Fetch only the **final checkpoint** (`.coor/.vel/.xsc`, ~140 MB) on the GPU pod, and
  leave the DCDs on the volume — they persist. Pull them later on a **CPU-only** pod
  (far cheaper) or when actually needed.
* The volume IS durable storage. Treat it as the archive of first resort and fetch lazily.
* Compress in flight (`rsync -z`); DCD is float32 and compresses poorly, so this is weak.

**Also note:** production's `_seed_from_parent` copies the parent's package on the volume
server-side, so the production pod does NOT re-upload — but the parent's final `.coor` must
be present LOCALLY for `build_replica_package` to seed from. So the fetch cannot simply be
skipped; it must be made selective.

