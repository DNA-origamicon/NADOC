# Kickoff — run + monitor the 0xT and 1xT 24hb 50 ns 4 fs production on RunPod

Copy everything below the line into a fresh session.

---

## ⏳ LIVE STATE (updated 2026-07-16 06:42) — BOTH PRODUCTIONS RUNNING

Both 50 ns 4 fs productions are launched and stepping cleanly on **RTX 5090** pods
(RTX 6000 Ada is currently UNAVAILABLE in EU-RO-1; 5090 is the sanctioned 2nd choice
per the user's Ada>5090>4500 order, and is the fastest of the three).

| variant | prod child job | pod | GPU | rate | seed frame |
|---|---|---|---|---|---|
| 0xT | `6fc87681f9de` | velgzf1e2ry3pq | 5090 $0.99/hr | 12.4 ms/step | MGHH_p100 |
| 1xT | `06fe9c9bff7a` | zwyw0rp0c9amya | 5090 $0.99/hr | 13.9 ms/step | MGHH_p10 (Tier-A early-stop terminus) |

- Data lands on `/media/jojo/Archive/nadoc_jobs/<child>/`. Each ~43–48 h → 50 ns; ~$43–48 each.
- **Watchdogs running (detached, survive session):** `watchdog.py 6fc87681f9de` and
  `watchdog.py 06fe9c9bff7a` — reap the pod on any persistent terminal state.
- On resume: `reap.py` (confirm exactly these 2 pods, nothing rogue), then
  `python watch.py <child> --oneline` each (coor grows, E finite/neg). On completion the
  launcher fetches + tears down; watchdog backstops at 18 min grace.
- **Final verification when both hit 12.5M steps / completed:** confirm trajectories +
  checkpoints on the Archive child dirs, `reap.py` → ZERO pods, `just test-smart` green.

### Two gotchas hit this session (NOT in the original handoff below — fix carried in code/notes)
1. **`launch_production.py` gained `--gpu-prefs "RTX 6000 Ada,RTX 5090"`** (ordered GPU
   priority). ⚠️ RunPod's `gpuTypeIds` list picks the **cheapest** available card, so NEVER
   put a cheaper fallback (4500 $0.74) in the same list as a preferred pricier card (Ada
   $0.77) — it silently takes the cheap one. Excluding 4500 → `[Ada,5090]` returns Ada if
   available else 5090; only if BOTH 500 do you relaunch with `--gpu-prefs "RTX PRO 4500"`.
2. **The reconcile snippet below (status→completed) is INSUFFICIENT.** `spawn_md_production`
   also needs the parent's **segment statuses = "done"** (not "pending"). AND: the teardown
   fetch pulls the *whole volume tree*, so stale MGHH p50/p100 `.coor` from a PRIOR ladder
   attempt land locally with a fresh mtime — do NOT blanket-mark all segments done (0xT was
   safe; 1xT was not). Seed from the segment the ladder ACTUALLY terminated at (watch.py's
   last "completed | <seg>" line). For 1xT that was MGHH_p10 (early-stop); p50/p100 → skipped.
3. **Sizing:** 1xT production first refused because it sized off the slow 4500 *ladder* rate;
   production runs on the fast 5090 — pass `--s-per-step 0.014` (measured 5090 prod rate).

---

Start and babysit a single **50 ns, 4 fs** NAMD production run for each of two validated 24hb
packages — **24hb_0xT** and **24hb_1xT** — on RunPod, landing trajectories on
`/media/jojo/Archive/nadoc_jobs/<job_id>/`. Both packages are already prepped and locally
validated; your job is to run the ladder (where needed) → production, and babysit to completion
WITHOUT reintroducing the billing/robustness bugs already fixed. Do NOT touch 2xT (a separate
local-validation track).

## ⛔ FIRST: `git pull --rebase origin master`, then read these — do NOT re-derive

- **`memory/project_extra_base_4fs_geometric_fixb.md`** — WHY 1xT works: the winning seed is the
  GEOMETRIC build + Fix B (heavy extra bases), NOT the oxDNA position-seed (that was the blocker).
- **`memory/feedback_runpod_babysitter_must_act.md`**, **`feedback_use_completion_triggers.md`**,
  **`REFERENCE_RUNPOD_RUNBOOK.md`**, **`LESSONS.md` L1–L10** — the billing/monitoring failure
  catalogue: a monitor must ACT on failure (reap the pod), use background completion triggers not
  foreground poll loops, never gate a wait-loop on `pgrep -f "<jobfile>"` (self-matches, hangs).
- **`memory/feedback_namd_4fs_production_only.md`** — 4.0 fs is the ONLY production dt.

## The two packages (both prepped, gate-passed, locally validated)

| variant | JOB_ID file / job_id | seed | ladder state | atoms |
|---|---|---|---|---|
| **0xT** | `JOB_ID_24hb_0xT` = `383f7dcc4a5d` | none (no extra bases) | **COMPLETE on the volume** (25 coor, through MGHH) | 1.32M |
| **1xT** | `JOB_ID_24hb_1xT_seeded` = `83a8ed8ded0e` | **geometric + Fix B** (338 extra T heavied x8) | NOT run yet (tiny-cycle validated on a real pod: 4 fs ladder survived k0.5/k0.1) | 1.38M |

Both were proven to hold a stable 4 fs step locally (full ladder + unrestrained MGHH) and the
full RunPod cycle was smoke-tested (stage→minimise→12 segments→teardown) with `e2e_24hb.py`.

## Run flow (per variant)

```bash
export PATH="$HOME/.local/bin:$PATH"; cd experiments/exp43_runpod_bench
python balance.py                                  # confirm funds (see budget below)

# 0xT: ladder already done → go straight to production. But the on-disk job status may be a
#      stale "running" from a prior session — reconcile it to completed first, else
#      launch_production refuses ("parent is running, not completed"):
python - <<'PY'
from pathlib import Path; import sys; sys.path.insert(0,'.'); sys.path.insert(0,'../..')
from backend.core.md_job import MdJob, MdStatus
j=MdJob.load('383f7dcc4a5d', Path('../../workspace'))
if j.status!=MdStatus.completed:
    j.status=MdStatus.completed; j.save(Path('../../workspace')); print('reconciled 0xT -> completed')
else: print('0xT already completed')
PY

# 1xT: run the FULL ladder first (on-demand, Tier-A early-stop, budget-capped), then production.
RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup \
  python launch_24hb.py 24hb_1xT_seeded --budget 30 > logs/relax_1xT.log 2>&1 &
RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup \
  python watchdog.py 83a8ed8ded0e --poll 90 --grace 1080 > logs/wd_1xT.log 2>&1 &

# When a variant's ladder is complete (watch.py shows the last MGHH segment done), launch its
# 50 ns production child on a fresh pod (rate/size read from the ledger + relaxation logs):
RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup \
  python launch_production.py --parent-stem 24hb_0xT     --ns 50 > logs/prod_0xT.log 2>&1 &
RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup \
  python launch_production.py --parent-stem 24hb_1xT_seeded --ns 50 > logs/prod_1xT.log 2>&1 &
```

**You can run 0xT and 1xT concurrently on separate pods — multi-pod async is validated** (two
pods on the shared network volume, separate job dirs, independent teardown).

## Babysit (the safety tooling is in place — USE it)

- **Monitor with BACKGROUND completion triggers**, not foreground polling. Watch, in the order
  that costs money: cumulative $ (`balance.py`, `reap.py`), each job ALIVE + PROGRESSING
  (`watch.py <job_id> --oneline` — the `coor` count grows, TOTAL finite/negative), pods count.
- **On any failure**, immediately reap the pod (targeted terminate by pod-id, or `reap.py --kill`
  if you are sure only your pods are live) — do not let it bill idle. Diagnose a segment failure
  with `peek_log.py <job> <segment_substr>`.
- **When done / on failure: confirm ZERO live pods** (`reap.py` → "nothing is billing").

## Budget

Balance at handoff: **~$195.95**. A 50 ns 4 fs production on the RTX PRO 4500 ($0.74/hr, the card
EU-RO-1 actually gives) is ~$60–100/variant → **~$120–200 for both**. It fits but is tight — top
up if you want headroom, and watch the cumulative ledger. `launch_production.py` sizes to the
remaining budget by default; pass `--ns 50` to force the full length and it will refuse if the
budget can't cover it.

## Gotchas this session hit (all real, all still apply)

- ⚠️ **Teardown fetch pulls the WHOLE output tree incl multi-GB DCDs** — slow, bills the pod at
  0% GPU during the fetch. `FETCH_TIMEOUT_S=900` bounds it, but once the checkpoint is back you
  can reap promptly (DCDs persist on the volume; pull later). **0% GPU after a ladder/production
  finishes = the fetch phase, NOT a hang** — the harness/watchdog tears the pod down.
- ⚠️ **`launch_24hb` can hang polling after an EARLY-STOPPED ladder completes** (its
  completion-detection vs Tier-A early-stop mismatch). If `watch.py` shows the last MGHH segment
  done but the launcher keeps polling, the watchdog will kill on grace — or reap the (idle) pod
  manually. This is the 0xT symptom from last session.
- ⚠️ **EU-RO-1 is flaky** (SSH channel drops, occasional pod host death). SSH-drop retry is in
  code; a full pod death → the run pauses resumable, just re-launch (the chain is idempotent, the
  volume holds completed steps). If it keeps dying to infra, wait for the region to settle.
- ⚠️ The network volume `77pnhye88p` PINS **EU-RO-1** (no H100/H200 there). The RTX PRO 4500
  ($0.74/hr) boots reliably.
- The `rebuild_enm_from_min` declash step is LOCAL-only (the pod chain doesn't run it), but the
  geometric+FixB 1xT build is clash-free so the pod runs the fast 4 fs ladder fine without it —
  validated on a real pod. Don't add it to the pod chain.

## Definition of done

- [ ] 0xT and 1xT each: **50 ns 4 fs production**, TOTAL finite/negative throughout.
- [ ] Trajectories + checkpoints on `/media/jojo/Archive/nadoc_jobs/<job_id>/`.
- [ ] `reap.py` reports ZERO live pods; `just test-smart` green.
- [ ] Report: $ spent vs budget, ms/step, ns achieved, where the data landed.
