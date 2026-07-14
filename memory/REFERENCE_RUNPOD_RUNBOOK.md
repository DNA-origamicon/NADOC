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

Run the gate. It mechanically checks everything that has bitten us:

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

```bash
python experiments/exp43_runpod_bench/prep_3x6x400.py     # free; ends in the gate
python experiments/exp43_runpod_bench/preflight.py <job>  # refuses a bad package
RUNPOD_API_KEY=$(cat ~/.runpod_key) nohup python .../launch_relax.py &
RUNPOD_API_KEY=$(cat ~/.runpod_key) nohup python .../supervise.py <job> &   # OWNS the pod
```

- **ON-DEMAND, not spot.** A reclaim restarts the interrupted segment from its TOP (no
  `.coor` until it completes) and chunks are 120k–600k steps. One reclaim costs more hours
  than spot saves dollars.
- **Always attach `supervise.py`.** The process that creates the pod is the ONLY thing that
  destroys it. See §4.
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

⚠️ **The on-pod kill-switch CANNOT stop the billing.** It runs on the pod with no API key:
it can kill NAMD, never the pod. Destruction lives in the launcher's `finally`. **If the
launcher dies, the pod bills an idle GPU forever** — and NAMD, being `setsid`-detached with
output on the volume, carries on perfectly happily, so nothing looks wrong.

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
