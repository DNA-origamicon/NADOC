---
name: REFERENCE_RUNPOD_RUNBOOK
description: The hardened protocol for running a production-scale NAMD job on a rented RunPod GPU — pre-flight gates, cost model, monitoring, teardown. Read BEFORE renting anything.
metadata:
  node_type: memory
  type: reference
---

# RunPod production run — the hardened protocol

Derived from the 3x6x400 run (2026-07-14): 1.94M atoms, full ladder + 5.5 ns production,
**$13 of a $15 cap**. That run found **eleven** bugs. **Nine of them produced no error of
any kind** — no crash, no failing test, no warning. They presented as *silence*: a correct
answer that was quietly the wrong one, or a bill that was quietly 4× too big.

> **The governing lesson.** A green test suite and a working small-scale e2e prove almost
> nothing about a rented-GPU run. The RunPod backend had a passing 6hb end-to-end
> (225k atoms, 5 min, $0.03) and was documented as "PROVEN on a live pod". Not one of the
> eleven bugs was reachable by it. **Scale, duration, and money each expose a disjoint
> class of failure.** Budget for finding bugs, not just for GPU-hours.

> **The second lesson.** *Fail-safe is not safe.* Two subsystems were documented as failing
> safe, and both did — into the most expensive possible behaviour. The early-stop
> evaluator's fail-safe is HOLD (run everything); on a rented pod that is a **budget
> event**, not a quality event. Always ask: *safe for whom — the science, or the wallet?*

---

## 0. Before you rent anything (all free)

**First, the balance — the one number that can kill a run, and the one nothing could see.**
RunPod destroys every pod the instant the balance hits zero, so a multi-day run that dies at
80% for want of credit wastes everything spent to that point.

```bash
python experiments/exp43_runpod_bench/balance.py --require 300   # exits non-zero if short
```

⚠️ **Balance lives ONLY on the legacy GraphQL API** (`myself { clientBalance }`). The REST API
this toolchain otherwise uses has **no billing endpoint at all**. And **you must call it with
`httpx`, never urllib** — `api.runpod.io` is behind Cloudflare, which 403s urllib's fingerprint
with body `error code: 1010`. **That is a bot-block, not a rejected key**, and mistaking one for
the other once had us defending a $7.96 balance figure when the true balance was $207.53 (see
LESSONS **L9**). `balance.py` **fails loud** — it refuses rather than warning-and-proceeding,
because on a rented GPU "fail-safe" means "fail-expensive" (§L1).

⚠️ **If this is a MULTI-VARIANT comparison, diff the prepped CONFS across variants before you
rent** (`timestep`, `rigidBonds`, `GPUresident`, `structure`). Designs that differ in one field
do NOT imply protocols that differ in one field: **extra crossover bases silently force the
declash protocol (1 fs, no HMR, no GPUresident), so a 0xT control runs a different integrator
from its 1xT/2xT variants** — confounding the very difference you are paying to measure, and
costing 4x on the variants that carry it. `preflight.py` catches the cost half; only a conf
diff catches the confound. See LESSONS **L8**.

⚠️ **`launch_production.py` sizes cost at `TIMESTEP_FS`=4 fs but does NOT verify the conf it
emits.** A **declash parent** (any design with extra crossover bases / unpaired runs) silently
yields a **1 fs, offload, no-GPUresident** child, so the launcher's dry-run ETA and $ are **~4×
optimistic** — the run dies at the kill-switch having produced ~¼ the ns you paid for, at **<20 %
GPU util** the whole time (a ~180 k-atom system in offload mode never fills a 4090; measured
2026-07-19: 6hb_2xT + 6hbx100_2xT both ran 1 fs at 12–17 % util, killed for $0-net after
diagnosis). Before the pod bills, confirm the PARENT manifest has `fast_relaxation.enabled=True`
(or `preflight.py` the child on its `fast=True` gate). **Fix a declash parent by rebuilding it
4fs-safe:** `prep_24hb_seeded.py <stem> --geometric` (geometric build + Fix-B heavy bases) →
`declash=False`, 4 fs, GPUresident. Proven to generalize beyond the 24hb (6hb_2xT: `declash=False,
timestep_fs=4.0, gpu_resident=True`). See `project_extra_base_4fs_geometric_fixb`.

Then run the gate. It mechanically checks everything that has bitten us:

```bash
python experiments/exp43_runpod_bench/preflight.py <job_id>
```

It refuses the run unless **all** of these hold. Each was learned by burning a real pod:

| gate | why | cost of skipping |
|---|---|---|
| **0 coincident heavy atoms** (<0.05 Å) | infinite VDW → NaN NAMD cannot explain | hours + a wedged pod |
| **min heavy-atom distance > 0.05 Å** | ditto. (3x6x400 measures **0.0993 Å** — the tight O2P↔O5' crossover contacts. Normal.) | as above |
| **`fast=True` in the package** | else 2 fs + offload + the HMR PSF referenced by nothing | **~4× the money for identical science** |
| **every chunk yields ≥ 20 ENERGY frames** | below `CutoffParams.min_frames` the early-stop evaluator refuses to judge → HOLD forever | **~4×**, silently |
| **`early_stop_relax=True`, tier `A`** | Tier B may not skip k<0.1, i.e. HALF the ladder | ladder impossible in budget |
| **job `archived` + `archive_path` set** | else `job_dir()` → the system disk | a full disk overnight |
| **arch of every offered GPU ∈ `NAMD_BUILD_ARCHS`** | a wrong-arch card rents FINE and dies at step 0 ("no kernel image is available") | a billing pod that computes nothing |
| **the ladder fits the budget at the MEASURED rate** | not the predicted one — see §2 | a truncated ladder |

**Prep is CPU work and it is FREE.** Never pay GPU rates to solvate. (GROMACS on 1.94M
atoms: ~1 min.)

---

## 1. The cost model (MEASURED, 3x6x400, 1.94M atoms, RTX PRO 4500 Blackwell, $0.74/hr secure)

| what | ms/step | note |
|---|---|---|
| minimisation | 2 fs, offload | **53.6** | ~5 min |
| **soft first chunk** | 1 fs, offload | **43–51** | **the most expensive chunk per ns, and unavoidable** — ~40% of a best-case ladder |
| every other chunk | **4 fs, GPU-resident** | **26.4** | **13.1 ns/day** |

⚠️ **The per-Matom fit does NOT transfer across GPU architectures.** The 4090's measured
11.2 ms/step/Matom predicted **20.9** ms/step; the Blackwell does **26.4** (1.26× slower).
**Re-measure on any new card before costing a run off it.**

⚠️ **You pay GPU rates to DOWNLOAD your results.** The network volume is reachable only
*through a live pod*, so `fetch_outputs` runs while the GPU bills, idle. 5.2 GB at domestic
downlink ≈ **100 min ≈ $1.20** — a quarter of what the science cost. **Fetch selectively:**
the final checkpoint is ~140 MB and is all production needs; the DCDs are the bulk and they
**persist on the volume**. Pull them later, or on the next pod (which is billing anyway).

**Real ladder economics (4 stages × 3 chunks, 4.8M steps at 4 fs):**

| | steps run | wall | cost |
|---|---|---|---|
| no early-stop | 4,800,000 | ~35 h | ~$26 |
| Tier B, best case | ~2,400,000 | ~18 h | ~$13 |
| **Tier A, measured** | **480,000** | **4.6 h** | **$3.99** |

Tier A skipped **4.32M of 4.8M steps** — every stage plateaued at its FIRST chunk (a **10×**
acceleration; exp36's 4.9× was pessimistic). **Tier A is not an optimisation. It is the
difference between the run existing and not.**

---

## 2. Launch

**App-managed launches now install RunPod's provider-side `terminateAfter` at pod
creation (2026-08-09).** The deadline is budget-derived per candidate card, persisted as
`MdJob.runpod_terminate_after`, and survives NADOC, SSH, the workstation and the container.
The on-pod NAMD lifetime watchdog remains independent redundancy. App launches are
on-demand; spot is refused because the provider-expiring GraphQL path is on-demand and a
reclaim can discard an unfinished segment.

```bash
python experiments/exp43_runpod_bench/prep_3x6x400.py     # free; ends in the gate
python experiments/exp43_runpod_bench/preflight.py <job>  # refuses a bad package
RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup python .../launch_relax.py &
# NO supervisor here. See below.
```

- 🛑 **DO NOT launch `supervise.py` alongside a healthy launcher.** The previous version of
  this runbook told you to, and **doing so destroys your own pod.** `supervise.py` ADOPTS a
  pod and then applies `run_job_on_pod`'s done-test to it. During STAGING — the several
  minutes the launcher spends SFTP-ing a 739 MB package — NAMD has not started, so the pod
  reports `state=unknown, segment=None, alive=False, stale=True`. The supervisor reads that
  as **"ladder finished"**, fetches, and **terminates the pod out from under the launcher**,
  which then dies with `upload failed: Connection not open`. Measured 2026-07-14: pod
  `aq6ri6d53kd6v0` destroyed **62 seconds** after creation, mid-upload.
  **`supervise.py` is a RE-ATTACH tool** (its own docstring says so) — for a pod whose
  launcher has ALREADY DIED. Keep it on standby; attach it only then.
- **ON-DEMAND, not spot.** A reclaim restarts the interrupted segment from its TOP (no
  `.coor` until it completes) and chunks are 120k–600k steps. One reclaim costs more hours
  than spot saves dollars.
- **App-managed pods are provider-bounded.** NADOC records the pod immediately and tears it
  down on completion, failure, or an explicit Stop. Once detached NAMD has been submitted,
  loss of NADOC/SSH is a handoff—not permission to kill healthy science. Reconnect adopts
  the job; `terminateAfter` remains the hard billing boundary if adoption never happens.
- **Legacy experiment launchers still own their pods.** Their `finally` destroys only pods
  they created (`pod_seen`), never a blanket sweep. If one dies, attach `supervise.py` or
  reap explicitly; do not assume it carries the app's provider deadline.
- ⚠️ **`spend_ledger.HARD_CAP_USD` is a real gate, and a stale one is a silent saboteur.**
  `launch_production.py` sizes production from `ledger.remaining()` and `supervise.py`
  DESTROYS the pod when `spent > HARD_CAP_USD`. The cap was $15 while the 24hb 0xT run alone
  costs ~$70 — production would have been truncated to a few percent of its length and
  reported as success. Raised to $120 (2026-07-14). **Check it covers the run before you
  launch.**
- The kill-switch is a **BUDGET**, not a duration: `lifetime_for_budget(usd, pod.cost_per_hr)`
  derives wall-clock from the rate of the card you ACTUALLY got.

---

## 3. Monitoring — `watch.py --oneline`

Check all five, in the order that costs money:

1. **COST** — cumulative across EVERY pod (the in-code kill-switch is per-POD and has no
   memory: two pods each get the full budget).
2. **ALIVE** — `kill -0 <pid>`. ⚠️ **NEVER `pgrep namd3`**: NAMD renames its process to
   `NAMD masterPe`, so pgrep matches NOTHING and reports a live job as dead.
3. **PROGRESS** — ENERGY frame count INCREASING; `.coor` count growing. Flat = wedged.
4. **SANITY** — latest TOTAL finite and negative. ⚠️ Find TOTAL **by name from the `ETITLE`
   header**, never by a hardcoded column index — counting columns by hand lands on TEMP,
   which is legitimately 0.0 during a minimisation, and the watchdog then screams
   "structure blew up" at a perfectly healthy run. *A false alarm that kills a good pod
   costs exactly as much as a missed real one.*
5. **STATUS** — the `nadoc_status` sentinel.

**Known-benign — do NOT panic-kill:**
- `Periodic cell has become too small` (**cell_shrink**): an NPT box relaxing ~3% to
  equilibrium density. Self-healing *only because* the retry now resumes from the segment's
  own restart files (§5). Measured: 156.6×89.1×1436.2 → 152.0×86.5×1393.4.

---

## 4. Teardown — the pod is the meter

```bash
python experiments/exp43_runpod_bench/reap.py           # list what is billing
python experiments/exp43_runpod_bench/reap.py --kill    # destroy everything
```

⚠️ **The on-pod kill-switch CANNOT stop billing.** It kills NAMD without an API key. For
current app-managed jobs the provider-side `terminateAfter` destroys the pod even if the
launcher dies; legacy/ad-hoc launchers without that field still require an owning finally
or explicit reaper.

| event | app-managed pod behavior |
|---|---|
| provisioning/staging fails before NAMD submission | terminate immediately |
| NAMD reports completed or failed | fetch when appropriate, then terminate immediately |
| user presses Stop | terminate immediately |
| NADOC reload, shutdown, API reconnect, or SSH/controller loss after submission | leave the pod running and adopt later |
| NADOC never returns | RunPod terminates at persisted `runpod_terminate_after` |
| on-pod lifetime expires first | kill NAMD; provider deadline still terminates the billing pod |

Creation uses RunPod GraphQL because the REST create schema does not accept
`terminateAfter`. Each ranked fallback GPU is attempted separately because the GraphQL
mutation accepts one GPU type. The deadline uses the budget and a conservative per-card
price ceiling; after allocation, the independent on-pod timer uses the pod's actual rate.

### Lifecycle attribution (2026-08-09)

NADOC appends every app-managed creation and termination transition to
`workspace/.runpod_lifecycle.jsonl` (mode `0600`). A termination is recorded *before* the
DELETE request and then as succeeded, already absent, or failed. Records include pod id,
job id when known, reason, provider deadline, and timestamp. This ledger survives the pod,
whose provider lifecycle fields disappear from the API after deletion.

When a recorded pod is absent from RunPod, NADOC now pauses the job, retains its last pod
id, and writes `pod_observed_missing` with one of three attributions:

- `nadoc_delete`: a matching `terminate_requested` record exists, including its reason;
- `external_or_unknown` with creation coverage: NADOC observed creation but issued no
  DELETE, so provider/host or account-side action is the likely cause;
- `external_or_unknown` without creation coverage: legacy pod, therefore inconclusive.

Disappearance no longer automatically rents another pod. Checkpoints remain on the network
volume and Resume requires fresh user authority, preventing an infrastructure loop from
spending the full budget once per replacement.

This happened: a transient DNS blip (`Temporary failure in name resolution`) on a routine
poll killed the launcher. `_request` now retries transient/5xx/429 (never 4xx). And the pod
id is now **persisted the instant it exists** — it wasn't, so the orphan could not even be
*named*, let alone reaped.

**Finish every run with `reap.py` and confirm `0 pods`.** Anything on the account is billing.

---

## 5. The failure catalogue — 11 bugs, 9 silent

| # | bug | how it presented | fix |
|---|---|---|---|
| 1 | `early_stop_relax` was a **no-op** on runpod | flag settable; nothing read it | port slurm's bridge emitters |
| 2 | Tier B may not skip k<0.1 — **half the ladder** | "early-stop is on" | Tier A mandatory |
| 3 | **`fast=True` silently disabled early-stop** | accelerator ran, always answered HOLD | `_output_freq` from chunk length |
| 4 | `cell_shrink` retry re-read the **ORIGINAL** box | "self-healing, bounded retry" = *fails 4×* | `remote_resume_conf.py` |
| 5 | **late** cell-shrink starves a resumed chunk of frames | as #3, different trigger | recompute cadence from REMAINING steps |
| 6 | `GPU_TYPES` held **community** prices in a secure-only world | estimates ~2.2× low | live-checked secure prices |
| 7 | production child dropped `archive_path` | trajectory → 20 GB system disk | inherit from parent |
| 8 | DNS blip **orphaned a billing pod** | pod unnameable, unkillable | retry + persist pod id |
| 9 | **the spend ledger FROZE** while a GPU billed | total stuck at $0.95; true $1.35 | collapse rows per pod |
| 10 | supervisor saved the job **before** deciding its status | finished ladder recorded as "running" | save AFTER deciding |
| 11 | `reap.py` didn't close the ledger | a destroyed pod accrued forever | close on reap |

**Only #4 announced itself.** Every other one was code that passed its tests and was
documented as working.

**Patterns to carry forward:**
- **Any step-denominated cadence is a latent bug the moment the timestep becomes a
  variable.** (#3, #5 — the same bug twice, from different triggers.)
- **A safety net can have the same hole as the thing it protects.** The spend ledger existed
  *because* the kill-switch had no memory — then it under-reported. **A ledger that
  under-reports is worse than no ledger, because it is trusted.** (#9)
- **A documented "self-healing"/"fail-safe" behaviour is worthless until something has
  watched it heal.** (#2, #3, #4)
- **Persist state the instant it exists, not when convenient.** (#8, #10)

---

## 6. Still open

- **Fetch is not selective** — you pay GPU rates for a bulk download (§1). Fix: fetch the
  checkpoint on the GPU pod; pull DCDs later / on a CPU pod / on the next pod.
- **Cumulative spend lives in an experiments script**, not the app. The real fix is
  `MdJob.spent_usd` accumulating across pods and SHRINKING the next pod's budget.
- **`fast=True` also halves the SOFT chunk's steps while its timestep stays 1 fs**, so the
  warm-up drops 240 ps → **120 ps** of simulated time. Errs toward *less* warm-up. A physics
  call, not a code one — unresolved.
- **The Clusters card / RunPod radio / pre-flight gate have never been clicked in a browser.**
  Everything above was driven from `experiments/exp43_runpod_bench/*.py`.

---

## 7. Small-box / sparse-box / autonomous selection (VoltronCore compact, 2026-07-24)

A 1.31M-atom **compact** run (23%-fill water-shell box, oxDNA-relaxed VoltronCore) re-learned a
stack of things §0–6 did not cover. §0–6 came from *full-box, H100, 3.0.2-release* runs; none of
its numbers or card choices transfer to a *sparse, small, cheap-card* run. The general rule
under all of this: **the fullbox bench predicted almost nothing about a different box on a
different card — re-measure resident-capability, timestep stability, AND rate empirically every
time, on the actual card class.** Reusable launcher: `launch_voltron_compact.py`.

**Build × box-fill decides GPU-resident — not the GPU.**
- The **3.0.2 release** dies at **step 0** on a sparse (water-shell/carved, <~90% fill) cell:
  `FATAL ERROR: Low global CUDA exclusion count! (N vs M)`. Fires on 4 fs AND 2 fs → it is NOT a
  timestep problem, it is resident-tiling on a vacuum-containing cell.
- The **Dec-2025 git build** does sparse-cell GPU-resident fine (that is literally what runs
  locally). **For any carved/shell box you must ship the git build**, or fall back to CUDA-offload
  (a different code path that tolerates sparse cells, ~2.6× slower). Switching GPU does NOT help —
  same 3.0.2 → same failure on any card.
- Package the git build once: `tar czf namd_git.tar.gz -C <build>/Linux-x86_64-g++ namd3`
  (302 MB→167 MB). It statically links CUDA; the pod needs only `apt-get install -y libtcl8.6
  libfftw3-single3`. Verify `ldd namd3 | grep 'not found'` is empty before trusting it.

**The git build is multi-arch sm_50…sm_90 — NO sm_120.** So the **RTX 5090 (Blackwell) cannot run
it.** "5090 or higher" is self-contradictory with the git build; usable cards top out at
sm_90 (H100/H200). Rebuilding NAMD +sm_120 = a multi-hour on-pod recompile — not worth it.
**Always arch-gate the offered card against the build's ACTUAL arch set** (git: {5.0,6.0,7.0,7.5,
8.0,8.6,8.9,9.0}; the multi-arch 3.0.2 tar: {8.0,8.9,9.0,12.0}).

**Best $/ns for a SMALL box is a cheap Ada/Ampere card, NOT an H100.** Measured on the 1.31M box,
4 fs GPU-resident: **RTX 4090 (sm_89, $0.69/hr) ≈ 24 ns/day ≈ $0.69/ns.** An H100 SXM is ~1.6×
faster wall-clock but ~5× the $/ns — its horsepower is wasted below a few M atoms. The
`gpu_value_is_two_axes` rule flips with box size: **H100/H200 win value only on the huge (10 M+)
boxes of §1; small boxes want the cheapest arch-compatible card that still fills.**

**Same GPU model, different pod = different rate — bench the ACTUAL pod.** The bench 4090 did
14.3 ms/step (24 ns/day); a *second* 4090 for the production run did 21.5 ms/step (**16 ns/day**) —
same conf, same box, ~1.5× slower, from RunPod's per-pod vCPU/host/thermal variance. **Size the run
from a rate measured on THE pod you are on, never a prior pod's.**

**Prove timestep stability ONCE, then FORCE it — do not re-probe every run.** 4 fs stability is a
*system* property (ssDNA + HMR + rigidBonds integrator), card-independent. The launcher's 20k-step
4 fs "probe" used a fixed **240 s wall-clock window**; on a slower card 20k steps don't finish in
240 s → "no verdict" → silent **conservative fallback to 2 fs = HALF speed**. Two fixes, both
applied: probe verdict must be **step-count based** (N clean steps), and once 4 fs is proven for a
system, pass **`--force-4fs`** to skip the probe entirely. (VoltronCore's free ssDNA: 4 fs is
PROVEN stable — force it.)

**Never let a fallback silently degrade value.** When the target 4090 was a dud, the launcher fell
back to an **A6000** (2× worse $/ns) AND its slow rate tripped the probe→2 fs fallback (another 2×)
= **4× worse than intended, silently**, at 2 ns/day. **Bound the fallback list to same-value-tier
cards; prefer retrying for the target card over renting a poor-value one.**

**Two launcher bugs that hung/failed the paid path (both fixed, keep the fix):**
- Backgrounded SSH launch (`setsid nohup … & echo $!`) occasionally returns **no channel-EOF** on
  a quirky/slow pod → `conn.run` times out even though the process started. **Tolerate the timeout
  and verify liveness separately** (deadman via its own log line; NAMD via log-file growth — never
  `pgrep namd3`, it renames to "NAMD masterPe", §3).
- **No-SSH dud pods** (rent RUNNING, never expose SSH within 900 s) are common. **Acquisition
  retry**: terminate the dud, rent a fresh pod, up to N attempts; set a `committed` flag at NAMD
  launch so a failure AFTER the run starts does NOT restart an expensive run.

**Teardown + deadman are proven (watched firing).** Across 4 induced failures + 3 clean runs,
`confirmed_pod`'s finally left **0 pods** every time; the **pod-side deadman self-terminated 78 s**
after the controller went dark (zero-secret, via the pod-injected key in `/proc/1/environ`); the
SANITY monitor caught an injected `Atoms moving too fast` and tore down. **Cheap preflight (~$1
over 8 pods) is worth it — it found both bugs and the wrong-config trap before the paid run.**

---

## 8. The unified pipeline (autonomous, no intervention)

The end-to-end order every RunPod NAMD job should follow — each stage encodes a §5/§7 lesson so
they are not re-learned. Driver: `experiments/exp43_runpod_bench/launch_voltron_compact.py`
(generalize per-job).

1. **ASSESS** — atom count + **box fill fraction** (`md_vram.carve_fill_fraction`). Fill <~90% →
   sparse → **git build (resident) or offload**; ≥90% → either build. Atom count → VRAM floor →
   min card memory. Look up (or probe once) timestep stability for the system.
2. **SELECT CARD** — poll RunPod for **available** GPU types + live prices; filter to
   `arch ∈ build.arches` AND `vram ≥ floor` AND in-stock; **rank by $/ns** (measured-rate registry
   per arch, else estimate). Small box → cheapest compatible; huge box → H100/H200. Fallback list =
   same-value-tier only. **Never a card outside the build's arch set** (silent step-0 death).
3. **PACKAGE** — stage the right NAMD build tar (git for sparse) + solvated system + confs + HMR
   PSF (for 4 fs). Compress the binary; verify `ldd … | grep 'not found'` empty on the pod.
4. **PREFLIGHT (cheap, on the chosen pod)** — arm deadman; a short run to **measure the REAL
   ms/step on THIS pod**, confirm resident works on this box, confirm the timestep holds (step-based
   probe). **Size the full run from the measured rate + budget.** Killswitch tests
   (`deadman_test.py`, `--inject-fail`) are generic — run once per toolchain change, not per job.
5. **RUN** — full production; monitors = budget + stall (flat step count) + blowup (BLOWUP_RE) kill,
   deadman heartbeat refresh each poll, **selective auto-fetch before teardown** (container disk
   dies with the pod), `confirmed_pod` prove-destroyed. `pod_watchdog.py` as the independent
   budget/age backstop. All autonomous; dud-retry throughout.

**Implemented** (`launch_voltron_compact.py`, spec-driven — pass a `JobSpec`, defaults to
VoltronCore compact; tests `test_runpod_select.py` + `test_runpod_launch_pipeline.py`):
- **ASSESS**: `natom_from_package` reads `!NATOM` from the package PSF (past the multi-thousand-line
  NTITLE block — a naive small read-cap misses it), so atom count is never hard-coded.
- **SELECT**: `backend/core/runpod_select.pick_cards` — live stock/price × `BUILD_ARCHS` × VRAM ×
  $/ns with a speed floor; returns a fast same-tier fallback list.
- **LEARN**: a per-arch rate registry (`gpu_rates.json`, running mean of accepted-run ms/step-per-
  Matom) refines the $/ns estimate + reroll floor over time — `record_rate` folds in each accepted
  run, `estimate_rate(registry=…)` uses it above 2 samples, else the conservative static prior.
  (Only ACCEPTED/post-reroll rates are recorded, so slow-pod outliers never pollute the mean.)
- **AUTO-REROLL** (the per-pod-variance fix): after warmup (~8k steps) it measures the REAL rate and,
  if `< reroll_floor × estimate_rate(card)` (default 0.7×), kills + rents a fresh pod — bounded by
  `--max-reroll` (default 2), then accepts the next pod as-is. This is what would have caught the
  16-ns/day dud 4090 automatically. A rerolled pod is terminated by `confirmed_pod` (no fetch).
