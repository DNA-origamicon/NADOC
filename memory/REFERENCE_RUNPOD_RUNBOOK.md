---
name: REFERENCE_RUNPOD_RUNBOOK
description: The hardened protocol for running a production-scale NAMD job on a rented RunPod GPU — pre-flight gates, cost model, monitoring, teardown. Read BEFORE renting anything.
metadata:
  node_type: memory
  type: reference
---

# RunPod production run — the hardened protocol

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Before renting, read the preflight, cost, launch, monitoring and teardown sections linked below. A stopped NAMD process is not a terminated billing pod. Preserve provider deadlines, ownership, lifecycle attribution and fresh authority for replacement rentals. Historical prices/results are dated evidence, not current quotes.

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
do NOT imply protocols that differ in one field. The current automatic declash threshold is
**per junction**: 0xT and 1xT use the standard ladder, while a junction carrying 2+xT uses the
2 fs rigid-bond gentle tier. Sequence-bearing extensions and an explicit `declash=true` also
select it. Several independent 1xT crossovers do not add together. This can still confound a
1xT/2xT comparison unless the emitted protocol is checked. `preflight.py` catches the cost half;
only a conf diff catches the physics confound. See LESSONS **L8**.

⚠️ **Never infer production cost from the design label or relaxation tier.** Production
timestep, rigid bonds, HMR, and GPU-resident mode are resolved independently and an HMR PSF can
be built on demand from a completed declash package. Inspect the generated child conf and run
`preflight.py` before renting. If a 2+xT design should avoid automatic declash, provide a validated
pre-relaxed seed (`pre_declashed=true`); do not simply relabel it 1xT or disable safety checks.
The historical geometric+Fix-B path and its measurements remain documented in
`project_extra_base_4fs_geometric_fixb`.

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

<a id="1-the-cost-model-measured-3x6x400-194m-atoms-rtx-pro-4500-blackwell-074hr-secure"></a>
- [1. The cost model (MEASURED, 3x6x400, 1.94M atoms, RTX PRO 4500 Blackwell, $0.74/hr secure)](details/REFERENCE_RUNPOD_RUNBOOK/01-1-the-cost-model-measured-3x6x400-194m-atoms-rtx-pro-4500-blackwe.md#1-the-cost-model-measured-3x6x400-194m-atoms-rtx-pro-4500-blackwell-074hr-secure)

<a id="2-launch"></a>
- [2. Launch](details/REFERENCE_RUNPOD_RUNBOOK/01-1-the-cost-model-measured-3x6x400-194m-atoms-rtx-pro-4500-blackwe.md#2-launch)

<a id="3-monitoring--watchpy---oneline"></a>
- [3. Monitoring — `watch.py --oneline`](details/REFERENCE_RUNPOD_RUNBOOK/01-1-the-cost-model-measured-3x6x400-194m-atoms-rtx-pro-4500-blackwe.md#3-monitoring--watchpy---oneline)

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

<a id="lifecycle-attribution-2026-08-09"></a>
- [Lifecycle attribution (2026-08-09)](details/REFERENCE_RUNPOD_RUNBOOK/02-lifecycle-attribution-2026-08-09.md#lifecycle-attribution-2026-08-09)

<a id="5-the-failure-catalogue--11-bugs-9-silent"></a>
- [5. The failure catalogue — 11 bugs, 9 silent](details/REFERENCE_RUNPOD_RUNBOOK/02-lifecycle-attribution-2026-08-09.md#5-the-failure-catalogue--11-bugs-9-silent)

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

<a id="7-small-box--sparse-box--autonomous-selection-voltroncore-compact-2026-07-24"></a>
- [7. Small-box / sparse-box / autonomous selection (VoltronCore compact, 2026-07-24)](details/REFERENCE_RUNPOD_RUNBOOK/03-7-small-box--sparse-box--autonomous-selection-voltroncore-compact.md#7-small-box--sparse-box--autonomous-selection-voltroncore-compact-2026-07-24)

<a id="8-the-unified-pipeline-autonomous-no-intervention"></a>
- [8. The unified pipeline (autonomous, no intervention)](details/REFERENCE_RUNPOD_RUNBOOK/03-7-small-box--sparse-box--autonomous-selection-voltroncore-compact.md#8-the-unified-pipeline-autonomous-no-intervention)
