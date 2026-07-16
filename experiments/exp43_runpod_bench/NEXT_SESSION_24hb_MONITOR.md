# Kickoff — fix the k=0.1 seed-clash, then launch + monitor the 24hb 4 fs campaign on RunPod

Copy everything below the line into a fresh session.

---

Run the 24hb extra-crossover-base MD campaign on RunPod: three variants (24hb_0xT, 24hb_1xT,
24hb_2xT), each a relaxation ladder then **50 ns of 4 fs production**, landing trajectories on
`/media/jojo/Archive`. **But first resolve the one open blocker** (below) — for the extra-base
variants a full ladder does NOT yet complete at 4 fs. Your job: fix that (locally, cheaply),
then launch + babysit to completion without reintroducing the billing/robustness bugs already
fixed.

## ⛔ FIRST: `git pull --rebase origin master`, then read these — do NOT re-derive

- **`experiments/exp43_runpod_bench/PIPELINE_4FS_EXTRA_BASES.md`** — the 3-part solved pipeline
  (seed-phosphate fix, heavy dangling bases, mass-consistent soft) + what's proven vs open.
- **`experiments/exp43_runpod_bench/NAMD_4FS_RATTLE_RESEARCH.md`** — the literature (27 sources).
- **`memory/feedback_namd_4fs_production_only.md`** — **4.0 fs is the ONLY acceptable production
  timestep.** Never propose a lower production dt; lower dt only in ramp/relax/anneal.
- **`memory/feedback_runpod_babysitter_must_act.md`**, **`feedback_use_completion_triggers.md`**,
  **`REFERENCE_RUNPOD_RUNBOOK.md`**, **`LESSONS.md` L1–L10** — the billing/monitoring failure
  catalogue. Especially: a monitor must ACT on failure (not just log); use background completion
  triggers, never foreground poll loops; NEVER gate a wait-loop on `pgrep -f "<jobfile>"` (it
  self-matches the watcher and hangs).

## State at handoff (commits `8691a65` + `08ba0fd`, tree clean)

**SOLVED + committed + RunPod-validated:** extra-base designs run stable 4 fs through the soft
stage and the **k=0.5 ENM 4 fs stages** — the deterministic extra-base blowup is gone. Fixes:
- seed-builder phosphate fix (`atomistic._build_extra_base_atoms`; 430→0 catastrophic stretches),
- **heavy dangling bases** (`write_hmr_psf(heavy_residues=…, heavy_factor=8)`; equilibrium-exact
  mass scale-up so the stiffness measurement is unchanged; residues via
  `namd_topology.extra_base_segid_resids`),
- mass-consistent soft segment (`prep_24hb_seeded.make_soft_confs_mass_consistent`).

**Billing/robustness fixed + committed:** `FETCH_TIMEOUT_S` bounds the teardown fetch;
`watchdog.py` is an active grace-based pod killer; transient SSH drops now reconnect+retry
(`RunpodConnection.run(retries=…)`, poll-loop `MAX_POLL_SSH_FAILURES`).

## ⛔ THE OPEN BLOCKER — fix this LOCALLY before spending on RunPod

The extra-base variants blow up at the **k=0.1 ENM stage** (`02_..._k0p1_p10`). Diagnosed by
local reproduction (this is the cheap way — do NOT burn RunPod on it):

- It is **oxDNA-seed DUPLEX base clashes** (e.g. two guanine rings at **2.53 Å** at a crossover
  junction), masked by the strong k=0.5 ENM and released catastrophically (70× over the velocity
  limit) when the ENM relaxes to k=0.1. **Not** water, not stochastic, not the extra bases.
- **`margin` does NOT help** — it does not change the GPUresident velocity ceiling (fixed 2500).
- **Minimize reduces severity but can't clear it** (70×→2.3×, whack-a-mole) because **the ENM
  restrains the structure back to the clashed seed reference**. 0xT (no seeding) has no such
  clashes and its ladder completes 4 fs fine.

**Recommended fix (iterate locally, free):** build the **ENM reference from a declashed
structure** — minimize WITHOUT the ENM (or with a short unrestrained soft) first, then build the
Aksimentiev ENM from the declashed coords — so the ENM stops enforcing the seed clashes.
Alternative: declash the seed backmap so it doesn't introduce duplex clashes at junctions.

**Local reproduction harness (no RunPod):** the exact failing state is on disk —
`/media/jojo/Archive/nadoc_jobs/ffa561ec075f/package/24hb_1xT_namd_solvated/output/24hb_1xT_01_300K_NPT_ENM_k0p5_p100.{coor,vel,xsc}`
feeds `…/24hb_1xT_02_300K_NPT_ENM_k0p1_p10.conf`. Symlink the package (PSF, `_hmr.psf`, PDB,
forcefield, `mgh_extrabonds.txt`, `24hb_1xT_k0.1.enm.extra`) + that checkpoint into a scratch
dir, truncate `run` to ~500, and `namd3 +p8 +devices 0 <conf>` on the local RTX 3080 Ti (~2 min
per test). It reproduces the k=0.1 clash blowup at ~step 26. Iterate the ENM-reference fix until
that runs clean, THEN re-prep and validate ONE variant on RunPod.

## Packages / job IDs

| variant | job_id | atoms | status |
|---|---|---|---|
| **0xT** | `383f7dcc4a5d` | 1.32M | no seeding → no k=0.1 blocker; verify its ladder + run production |
| **1xT** | `ffa561ec075f` | 1.58M | heavy-base pipeline + margin; **blocked at k=0.1** until the ENM-ref fix; re-prep after the fix |
| **2xT** | — | ~2.6M | **RE-PREP** with the full pipeline once the fix lands: `prep_24hb_seeded.py 24hb_2xT a1f2ae5e40be --padding 1.0` |

Re-prep after fixing the ENM reference (regenerates the ladder confs):
`python experiments/exp43_runpod_bench/prep_24hb_seeded.py 24hb_1xT e53ba589d778 --padding 1.0`
then `preflight.py <new_job_id>` (must PASS: seed-health <5 Å, all GPUresident confs 4.0 fs).

## Launch + BABYSIT (the safety tooling is in place — USE it)

```bash
export PATH="$HOME/.local/bin:$PATH"
python experiments/exp43_runpod_bench/balance.py --require 320   # top-up gate; ~$300 for 3×50 ns
python experiments/exp43_runpod_bench/preflight.py <job_id>      # mechanical refuse-bad-package
# launch the ladder (loads JOB_ID_<stem>_seeded; interruptible=False/on-demand):
RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup \
  python experiments/exp43_runpod_bench/launch_24hb.py 24hb_1xT_seeded --budget 20 > logs/relax.log 2>&1 &
# ATTACH the active watchdog (grace-based, safe alongside a healthy launcher):
RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup \
  python experiments/exp43_runpod_bench/watchdog.py <job_id> --poll 90 --grace 1080 > logs/wd.log 2>&1 &
```

- **Monitor with a BACKGROUND completion trigger**, not foreground polling. Watch (in the order
  that costs money): balance/cumulative $ (`balance.py`, `reap.py`), the job is ALIVE and
  PROGRESSING (`watch.py <job> --oneline` — `coor` count grows), TOTAL finite/negative.
- **On any failure**, immediately reap the pod (`reap.py --kill`) — do not let it bill idle.
  Diagnose a segment failure cheaply with `peek_log.py <job> <segment_substr>` (reads the log off
  the volume via a short cheapest-card pod; confirms 0 pods after).
- **When done / on failure: `reap.py` must report ZERO live pods.**

## RunPod pitfalls this session hit (all real)

- ⚠️ **EU-RO-1 was flaky** — 3 of 4 launches died to infra (2 SSH channel drops, 1 pod host
  death). SSH-drop retry is now in code; a full pod death is beyond retry → the run pauses
  resumable (re-launch; the chain is idempotent, the volume holds completed steps). If it keeps
  dying to infra, wait for the region to settle rather than hammering it.
- ⚠️ **The teardown fetch pulls the WHOLE output tree incl. DCDs** (slow, bills the pod). It's
  now bounded by `FETCH_TIMEOUT_S=900`, but a failed run doesn't need the DCDs — consider
  reaping promptly once you have the result (DCDs persist on the volume; pull later). *(Follow-up:
  make teardown fetch the checkpoint only.)*
- ⚠️ Network volume `77pnhye88p` PINS **EU-RO-1** (no H100/H200 there). Cards: **RTX PRO 4500**
  ($0.74/hr) boots reliably; cheaper cards sometimes come up RUNNING but never start sshd.
- Balance at handoff **$197** — enough for validation + one variant, NOT the full 3×50 ns (~$300).

## Definition of done

- [ ] ENM-reference fix lands (extra-base ladder completes 4 fs locally, then on RunPod).
- [ ] 3 variants, 50 ns 4 fs production each, TOTAL finite/negative throughout.
- [ ] Trajectories + checkpoints on `/media/jojo/Archive/nadoc_jobs/<job_id>/`.
- [ ] `reap.py` reports ZERO live pods; `just test-smart` green; topic files updated.
- [ ] Report: $ spent vs budget, ms/step, ns achieved, where data landed.
