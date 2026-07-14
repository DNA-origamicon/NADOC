# Kickoff prompt — 24hb extra-crossover-base MD (0xT / 1xT / 2xT, 50 ns each)

Copy everything below the line into a fresh session.

---

Run the 24hb extra-crossover-base MD campaign on RunPod: build the 0xT and 2xT design
variants, prep + pre-flight all three, run **50 ns of production each**, babysit them to
completion, and land the trajectories on the archive drive.

## ⛔ BLOCKER — CHECK THIS FIRST, BEFORE ANY WORK

**The RunPod balance is $7.96. This campaign costs $196–262. It WILL stall.**

```bash
RUNPOD_API_KEY=$(cat ~/.runpod_key) uv run python -c "
import os,httpx; k=os.environ['RUNPOD_API_KEY']
print(httpx.post(f'https://api.runpod.io/graphql?api_key={k}',
  json={'query':'{ myself { clientBalance } }'},timeout=30).json()['data']['myself']['clientBalance'])"
```

If it is under ~$300, **STOP and tell the user to top up.** Do not start a run you cannot
finish — a pod that dies at 80% for lack of credit wastes everything spent to that point.
(RunPod terminates pods when the balance hits zero.)

## READ FIRST — do not re-derive any of this

* **`memory/REFERENCE_RUNPOD_RUNBOOK.md`** — the hardened protocol. Pre-flight gates, the
  measured cost model, monitoring, teardown, and the full failure catalogue.
* **`memory/LESSONS.md` category L (L1–L7)** — indexed by symptom.
* **`memory/project_runpod_submission.md`** (head only — never the archive).
* **`memory/project_bundle_stiffness_params.md`** and
  **`memory/project_crossover_parameterization.md`** — why this campaign exists and what
  the parameters are for.

A previous session ran a full 1.94M-atom ladder + production on RunPod and found
**nineteen bugs — seventeen of which produced no error of any kind.** They are all fixed
and pinned by tests. Your job is to *not reintroduce them*, not to rediscover them.

## Why 24hb (settled with data — do not re-litigate)

The parameters we need are the **inter-helix 6-DOF stiffnesses by CONTEXT** (how many
crossover neighbours each helix has). The stiff **3-3** context is the one that matters for
a real bundle's interior — its lateral stiffness is **~45× larger than 2-2** — and it is
exactly the one we have almost no data for:

| design | helices | bp/helix | atoms | 2-2 | 2-3 | **3-3** |
|---|---|---|---|---|---|---|
| 6hb ring | 6 | 116 | 314k | 6p | — | **0 pairs** ← useless |
| 10hb *(our current 0T source)* | 10 | 42 | 190k | 6p | 4p | **1 pair / 4 xo** ← the bottleneck |
| 18hb | 18 | 399 | 2.98M | 9p | 6p | 6 pairs |
| **24hb_1xT** | **24** | **147** | **1,322,736** | 6p | 12p | **12 pairs / 148 xo** |

24hb gives **12× the 3-3 pairs of 10hb**. ESS scales with independent pairs, so 10hb's
304 ns of 3-3 statistics is matched in **~25 ns** here; **50 ns roughly doubles our
best-ever 3-3 sampling**. It is also already a 1xT design (338 of 384 crossovers carry an
extra T), it is short enough to be affordable, and 147 bp/helix gives a real interior.

SNUPI's own protocol (ACS Nano 2021, Methods) is *"at least 100 ns per structural motif"* —
**50 ns on 24hb is better converged than that**, because SNUPI's constructs had far fewer
pairs. Do not pad to 100 ns without a reason.

## Step 1 — build the 0xT and 2xT variants (free, local)

`workspace/24hb_1xT.nadoc` exists. `extra_bases` on a `Crossover` is a **string or None**:

```
24hb_1xT: Counter({'T': 338, None: 46})
```

Create, from the SAME design (so the ONLY difference is the extra bases):
* `workspace/24hb_0xT.nadoc` — every `extra_bases` → `None`
* `workspace/24hb_2xT.nadoc` — every crossover that is currently `'T'` → `'TT'`

⚠️ Leave the 46 `None` crossovers alone in the 2xT variant — they are `None` for a reason;
changing them changes the topology, not the motif. **Read
`memory/feedback_crossover_no_reasoning.md` before touching any crossover code, and if you
are unsure about strand polarity or which crossovers may be edited, ASK — do not reason it
out.** Verify afterwards that all three designs have **identical helix/crossover topology**
and differ *only* in `extra_bases`.

## Step 2 — prep + PRE-FLIGHT all three (free)

```bash
# prep with fast=True  (4 fs + HMR + GPUresident) and early_stop_relax=True, tier A,
# archived=True on /media/jojo/Archive/nadoc_jobs/<job_id>
# — copy experiments/exp43_runpod_bench/prep_3x6x400.py; it does ALL of this correctly.

python experiments/exp43_runpod_bench/preflight.py <job_id>     # MUST pass. It exits non-zero.
```

`preflight.py` mechanically refuses a run that would silently cost 4×, land on the system
disk, or rent a card the binary cannot execute. **It is not optional.** It catches the exact
bug that cost the last session a night (starved early-stop frames).

## Step 3 — run

Per variant: relaxation ladder (Tier-A early-stop; it bridged 4/4 stages last time and cut
the ladder 10×), then a **50 ns production child**.

**Cards — the user has approved the faster ones. Prefer them when available:**

| card | arch | $/hr | ms/step @1.32M | ns/day | $/ns | 50 ns |
|---|---|---|---|---|---|---|
| **RTX PRO 6000** | sm_120 | 1.99 | **12.6** | **27.4** | 1.75 | **1.8 days** |
| RTX PRO 4500 | sm_120 | 0.74 | 25.4 | 13.6 | **1.31** | 3.7 days |

Compute does **not** scale with cost (2.69× the price → 2.01× the speed), so the PRO 6000
is ~34% worse per ns but **half the wall-clock**. Take it — the user has approved it and
wall-clock is the binding constraint here. Fall back to the PRO 4500 on stock.

The NAMD binary now covers **sm_80 / sm_89 / sm_90 / sm_120**
(`/workspace/namd/3.0.2p1-cuda-a80/namd3`). The A100 is therefore usable (1.39/hr) but is
**worse value than the PRO 6000** — and EU-RO-1 stock for everything churns by the minute,
so use `--retry-min`.

**Budget: ~$70–90 per variant at 50 ns. Track cumulative spend across EVERY pod with
`experiments/exp43_runpod_bench/spend_ledger.py`.** The in-code kill-switch is **per-pod and
has no memory** — two pods each get the full budget.

## Step 4 — babysit (this is most of the job)

`watch.py --oneline` every ~15 min. Check ALL of:

1. **COST** — cumulative across every pod. And the RunPod **balance**.
2. **ALIVE** — `kill -0 <pid>`. ⚠️ **NEVER `pgrep namd3`** — NAMD renames itself to
   "NAMD masterPe", so pgrep matches nothing and reports a live job as dead.
3. **PROGRESS** — ENERGY frames increasing, `.coor` count growing. Flat = wedged.
4. **SANITY** — TOTAL finite and negative. Find it **by name from the `ETITLE` header**,
   never by column index.
5. **STATUS** — the `nadoc_status` sentinel.

**Known-benign — do NOT panic-kill:** `Periodic cell has become too small` (an NPT box
relaxing ~3%). It now self-heals — the retry resumes from the segment's own restart files.

**Always attach `supervise.py <job_id>`** — the process that creates a pod is the only thing
that destroys it.

## THE TRAPS — every one of these was a real, billing failure

* ⚠️ **A cleanup routine must never have a blast radius larger than what it owns.**
  `supervise.py`'s `finally` used to destroy EVERY pod on the account; SIGTERM-ing one
  stale supervisor killed an unrelated production run at 62%. Fixed — **do not widen it
  again.** `reap.py --kill` is the all-pods panic button and is opt-in on purpose.
* ⚠️ **"Fails safe" can mean "fails EXPENSIVE."** Tier-A early-stop fails safe to HOLD (run
  everything) — right for the science, ~4× the bill. `_ensure_mdanalysis` is a HARD gate for
  this reason: a pod that cannot import MDAnalysis refuses to launch.
* ⚠️ **A ledger that under-reports is worse than no ledger, because it is trusted.** The
  spend ledger froze at $0.95 while a real GPU billed to $1.35. Pods bill from CREATE, not
  from the yield — a pod that never provisions still bills.
* ⚠️ **`cuobjdump --list-elf` LIES about arch coverage** — it unions NAMD's kernels with
  NVIDIA's bundled libs. The only proof is running the card.
* ⚠️ **Never size production from a relaxation rate.** Production deliberately runs a more
  expensive integrator (`fullElectFrequency 1`, `stepspercycle 10`) — ~1.35× slower. That
  mis-sized a run 2×.
* ⚠️ **Any step-denominated cadence is a latent bug the moment the timestep is a variable.**
  This bit twice (`fast=True` silently disabled early-stop; a late cell-shrink starved a
  resumed chunk of frames).
* ⚠️ **You pay GPU rates to DOWNLOAD results** (the volume is only reachable through a live
  pod). Fetch the final checkpoint (~140 MB); leave the DCDs on the volume and pull them
  later. The last session burned ~$1.20 downloading 5.2 GB with the GPU idle.

## Definition of done

- [ ] Three designs (0xT/1xT/2xT) differing ONLY in `extra_bases`, topology verified identical
- [ ] `preflight.py` passes for all three
- [ ] 50 ns production complete for each, TOTAL energy finite/negative throughout
- [ ] Trajectories + final checkpoints on `/media/jojo/Archive/nadoc_jobs/<job_id>/`
- [ ] **`reap.py` reports ZERO live pods** — anything left is billing
- [ ] Report: actual $ spent vs budget, measured ms/step, ns achieved, where the data landed
- [ ] `just test-smart` green; memory topic file updated with what you learned

## Scripts (all in `experiments/exp43_runpod_bench/`)

`prep_3x6x400.py` (template — free, ends in the degeneracy gate) · **`preflight.py`** (refuses
a bad run) · `launch_relax.py` · `launch_production.py` (self-sizing) · **`supervise.py`**
(owns the pod; ALWAYS attach) · `watch.py --oneline` · **`reap.py --kill`** (panic button) ·
`spend_ledger.py` (cumulative, session-wide) · `bench_gpus.py` (`--retry-min` for stock) ·
`build_namd_multiarch.py`.

## State as of handoff (2026-07-14 ~14:50)

* Git HEAD `b6f8590`, tree clean, `just test-smart` green (5010 passed).
* A 3x6x400 production run (`6ffc39e13a0d`) is **still running** on pod `wel852jxxb1w1t`
  (~$0.74/hr, ETA ~18:15). **Leave it alone.** It has its own supervisor. Do not reap it.
* RunPod balance **$7.96** — see the BLOCKER at the top.
* NAMD on the volume: `/workspace/namd/3.0.2p1-cuda-a80/namd3` (sm_80/89/90/120).
* Network volume `77pnhye88p`, **EU-RO-1** — it PINS the datacenter. H100/H200/B200 are not
  available there at all; do not plan around them.
