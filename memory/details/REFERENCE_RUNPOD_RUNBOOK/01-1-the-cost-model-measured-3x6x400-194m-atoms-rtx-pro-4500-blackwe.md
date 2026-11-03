# 1. The cost model (MEASURED, 3x6x400, 1.94M atoms, RTX PRO 4500 Blackwell, $0.74/hr secure) — supporting detail

[Topic head](../../REFERENCE_RUNPOD_RUNBOOK.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
