# Kickoff — launch & manage the 24hb 0/1/2xT MD campaign on RunPod (4 fs production)

Copy everything below the line into a fresh session.

---

Launch and babysit the 24hb extra-crossover-base MD campaign on RunPod: three variants
(24hb_0xT, 24hb_1xT, 24hb_2xT), each a relaxation ladder then **50 ns of 4 fs production**,
then land the trajectories on the archive drive. The packages are already prepped and
preflight-clean. Your job is to launch, babysit to completion, and not reintroduce any of
the billing/silent-failure bugs the runbook catalogues.

## ⛔ BLOCKER — CHECK FIRST

```bash
export PATH="$HOME/.local/bin:$PATH"
python experiments/exp43_runpod_bench/balance.py --require 320
```

Balance was **$200.43** at handoff; the campaign is **~$300 (3 × ~$90 for 4 fs / 50 ns at
~2.3M atoms) + ~$15 ladders + fetch**. RunPod destroys pods at $0 balance, so a run that
dies at 80% wastes everything spent. **If `balance.py --require 320` refuses, tell the user
to top up before launching anything.** balance.py uses httpx (urllib gets a Cloudflare
403/"error code: 1010" — that is NOT a bad key; see LESSONS L9).

## READ FIRST — do not re-derive

- **`memory/REFERENCE_RUNPOD_RUNBOOK.md`** — the hardened protocol (pre-flight gates, cost
  model, monitoring, teardown, the 11-bug + L8/L9/L10 failure catalogue). §0 has the balance
  gate and the multi-variant conf-diff warning.
- **`memory/LESSONS.md` L1–L10** — indexed by symptom. Especially **L10** (never attach
  supervise.py to a healthy launcher — it destroys your own pod), **L8** (extra bases
  silently veto the fast integrator), **L9** (Cloudflare 1010 ≠ auth), **L5** (a trusted
  under-reporting ledger), **K5** (`pgrep -il`, never `pgrep namd3` — NAMD renames to
  "NAMD masterPe").
- **`memory/project_crossover_parameterization.md` / `project_bundle_stiffness_params.md`** —
  why this campaign exists (inter-helix 6-DOF stiffness by crossover context; 24hb gives 12
  independent 3-3 pairs / 148 crossovers — 12× 10hb).

## Why 4 fs needs oxDNA seeding (the whole reason these packages exist)

The extra crossover bases are built by a geometric best-guess that **stacks neighbouring
extra-base sugars on top of each other** (measured: 159 clash pairs, C4'–C4' to 0.29 Å). The
declash minimiser then relieves the overlap by **stretching a C4'–C5' bond to a stable
force-balanced ~3.1 Å** — fatal to a 4 fs rigid-bonds RATTLE step, and unphysical (corrupts
the local stiffness) even at 3 fs. No relaxation escapes it (mass/HMR, PME cadence, Langevin,
annealing, full ladder all ruled out — it is a bad INITIAL guess).

**The fix (built + validated this session):** relax the design in oxDNA, then reconstruct the
NAMD starting structure from the relaxed coords (`build_namd_seed` → cg-spline backmap). That
places the extra bases at their true declashed positions (0 catastrophic stretches) so 4 fs
runs. New machinery:
- `backend/core/oxdna_seed.py` — `reorient_to_principal_axes` (long axis → z, shrinks the
  solvation box ~1.5×) + `separate_coincident_atoms` (nudges apart rare backmap coincidences).
- `backend/core/md_protocols.py` — a `pre_declashed` flag on `prepare_mgh_slow_release`
  (skips the soft 1 fs declash ladder for a seeded design → 4 fs fast ladder), and the
  **ladder ENM now excludes the ss extra bases** so a seeded fast ladder doesn't restrain
  them into a stretch.
- `experiments/exp43_runpod_bench/prep_24hb_seeded.py` — the seeded prep
  (`prep_24hb_seeded.py <stem> <oxdna_job_id> --padding 1.0`).
- `experiments/exp43_runpod_bench/oxdna_relax_design.py` — headless oxDNA relax
  (`oxdna_relax_design.py <stem>`; mc=1000, md_relax=1e6 CUDA, equil=1e5 CUDA — ~4 min).

⚠️ **The seeded boxes are BIGGER (2.3M / 2.6M atoms vs the 1.32M ideal-B-DNA build) and that
is CORRECT, not bloat.** The extra bases add slack and the bundle relaxes wider; the oxDNA
seed sizes the box to the real equilibrium envelope. A compact ideal-B-DNA box would be
undersized and the structure would expand into it during production. At the correct box size
4 fs genuinely wins (25% fewer steps than a correctly-sized 3 fs run).

## State at handoff — prepped job IDs

| variant | job_id | atoms | seed | status |
|---|---|---|---|---|
| **0xT** | `383f7dcc4a5d` | 1.32M | none (no extra bases) | **ladder DONE** (4 fs); production pending |
| **1xT** | `ffa561ec075f` | 1.58M | oxDNA `e53ba589d778` | **HEAVY-BASE PIPELINE 2026-07-15** — clean seed + heavy dangling bases + mass-consistent soft; preflight PASS; **RunPod full-ladder validation pending** |
| **2xT** | `bde4c57977fd` | 2.62M | oxDNA `a1f2ae5e40be` | ⚠️ built BEFORE the seed/heavy-base pipeline — **RE-PREP IT** (below, seed `a1f2ae5e40be`) before launch |

- **Read `PIPELINE_4FS_EXTRA_BASES.md`** — the full robust 4 fs pipeline (three distinct causes,
  three fixes) and what is proven vs what the RunPod full-ladder run must confirm/tune.
- 4 fs on extra-base designs needed **three** fixes, all now in code: (A) the seed-builder
  phosphate fix (`atomistic._build_extra_base_atoms`; 430→0 catastrophic stretches — old buggy
  seeds `f1c3a50c03c0`/`749cd6fcc58b`/`e76328d67512` are superseded); (B) **heavy dangling bases**
  (`write_hmr_psf(heavy_residues=…, heavy_factor=8)` — their fast torsional modes blow a 4 fs step
  and HMR lightens them; scaling their mass UP is equilibrium-exact, so the stiffness measurement
  is untouched); (C) a **mass-consistent soft segment** (soft stage uses the heavy-HMR PSF so the
  soft→4 fs hand-off doesn't make the 8×-heavy bases 8× hot).
- ⚠️ **The RunPod run is the VALIDATION.** Fixes A/B/C are proven locally (geometry clean, extra
  bases stable at 4 fs, preflight PASS) but end-to-end 4 fs over the real 120 ps+ graded-ENM
  ladder — and the `HEAVY_XB_FACTOR` value — must be confirmed on the ladder. **Run a short 4 fs
  probe off the equilibrated ladder BEFORE committing to 50 ns.** Only 4 fs production is
  acceptable (`memory/feedback_namd_4fs_production_only.md`); never lower the production dt.
- `0 pods live`, balance $200.43. NAMD on the volume: `/workspace/namd/3.0.2p1-cuda-a80/namd3`
  (sm_80/89/90/120). Network volume `77pnhye88p` pins **EU-RO-1** (no H100/H200/B200 there).
- ⚠️ **Uncommitted work.** `backend/core/oxdna_seed.py`, `backend/core/md_protocols.py`,
  `experiments/exp43_runpod_bench/*seeded*.py`, memory files are NOT committed. Pull/commit
  per the two-computer protocol before/after (`git pull --rebase origin master`).

### Re-prep 2xT first (it predates the final ENM fix)
```bash
export PATH="$HOME/.local/bin:$PATH"
python experiments/exp43_runpod_bench/prep_24hb_seeded.py 24hb_2xT a1f2ae5e40be --padding 1.0
python experiments/exp43_runpod_bench/preflight.py $(cat experiments/exp43_runpod_bench/JOB_ID_24hb_2xT_seeded)
```
(0xT and 1xT are already final. If you re-prep 1xT for any reason, seed from `e53ba589d778`.)

## Launch — per variant

Cards: prefer **RTX PRO 6000** ($1.99/hr) for wall-clock but EU-RO-1 almost never has it —
you WILL get the **RTX PRO 4500** ($0.74/hr) fallback, which is fine and better $/ns. The
`launch_24hb.py` GPU priority list + `_plan_fast` already lift the $1/hr ceiling and try
PRO 6000 → A100 → … → PRO 4500 → 4090.

```bash
# 0. gate every job (mechanical; refuses a bad package)
python experiments/exp43_runpod_bench/preflight.py <job_id>

# 1. relaxation ladder (Tier-A early-stop — MANDATORY, bridges ~4/4 stages, ~$5)
RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup \
  python experiments/exp43_runpod_bench/launch_24hb.py 24hb_1xT > logs/relax_1xT.log 2>&1 &
#   (for 0xT the ladder is already done — skip to production, seeded from 383f7dcc4a5d)

# 2. when a ladder completes -> production child (self-sizing off the remaining budget).
#    launch_production.py is wired to the 3x6x400 parent; for the 24hb variants, spawn the
#    production child from the completed ladder job the same way (spawn_md_production +
#    run_job_on_pod, execution_target=runpod, archived inherited). Size to 50 ns / 4 fs.
```

- **ON-DEMAND, not spot** (a reclaim restarts the interrupted segment from its top).
- **The launcher owns the pod; it destroys ONLY the pods it created.** 🛑 **Do NOT attach
  `supervise.py` to a healthy launcher — it will destroy your own pod mid-stage (L10).** It
  is a RE-ATTACH tool: use it ONLY if a launcher process has died and left a pod billing.
- Spend ledger cap is **$120** (`spend_ledger.HARD_CAP_USD`) — raise it if the full 3-variant
  campaign needs more, but keep it well under the balance so a runaway still stops.

## Babysit — `watch.py <job_id> --oneline`

Check, in the order that costs money:
1. **COST** cumulative across every pod, and the **balance** (`balance.py`).
2. **ALIVE** `kill -0 <pid>` — ⚠️ NEVER `pgrep namd3` (it renames to "NAMD masterPe"; use
   `pgrep -il namd`).
3. **PROGRESS** ENERGY frames increasing; `.coor` count growing. Flat = wedged.
4. **SANITY** latest TOTAL finite + negative — find it BY NAME from the ETITLE header, never
   by column index (that lands on TEMP = 0.0 during minimisation → false alarm).
5. **STATUS** the nadoc_status sentinel.

`watch.py <job_id>` now takes the job id as an argument (fixed this session — it used to
ignore argv and always watch the 3x6x400 job). Benign, do NOT panic-kill:
`Periodic cell has become too small` (NPT box relaxing ~3%, self-heals).

## Traps — every one was a real billing/correctness failure

- ⚠️ **A stuck fetch bills an idle pod indefinitely.** A resume/fetch SFTP channel HUNG this
  session; the pod billed until terminated by hand. If `watch.py` shows the run COMPLETED but
  a pod is still live and the launcher log is stuck mid-fetch, terminate that ONE pod directly
  (`client.terminate_pod(pid)` — targeted, NOT `reap.py --kill` which is all-pods) and clean
  up the launcher. The DCD you need is usually already on the archive; verify before killing.
- ⚠️ **You pay GPU rates to download.** Fetch the final checkpoint (~140 MB); DCDs persist on
  the volume — pull them later / on the next pod. A resume RE-FETCHES the whole DCD (wasteful).
- ⚠️ **Everything downloaded goes on `/media/jojo/Archive`, never the ~92%-full system disk**
  (`feedback_runpod_downloads_to_archive`). All jobs are `archived=True`; verify a fetch's
  landing path starts with `/media/jojo/Archive`.
- ⚠️ **Never size production from a relaxation rate** (production runs a costlier integrator,
  `fullElectFrequency 1` — ~1.35× slower). Size from a production measurement (L7).
- ⚠️ **`cuobjdump --list-elf` LIES about arch coverage** — only running the card proves it.

## Definition of done
- [ ] 3 variants, 50 ns 4 fs production each, TOTAL finite/negative throughout.
- [ ] Trajectories + final checkpoints on `/media/jojo/Archive/nadoc_jobs/<job_id>/`.
- [ ] **`reap.py` reports ZERO live pods** — anything left is billing.
- [ ] Report: $ spent vs budget, measured ms/step, ns achieved, where data landed.
- [ ] The three variants differ ONLY in `extra_bases` (topology identical — verified: hash
      `96b9d936…`); the stiffness comparison is by crossover context (2-2 / 2-3 / **3-3**).

## Scripts (all in `experiments/exp43_runpod_bench/`)
`prep_24hb_seeded.py` (seeded prep) · `oxdna_relax_design.py` (headless oxDNA relax) ·
**`preflight.py`** · `launch_24hb.py` (relax ladder, PRO-6000-first + $2.10 ceiling) ·
`launch_production.py` (self-sizing; wired to 3x6x400 — adapt for the 24hb parents) ·
`resume_job.py` (resume a partial run) · **`supervise.py`** (RE-ATTACH ONLY — never on a live
launcher) · `watch.py <job> --oneline` · `balance.py --require N` · `reap.py --kill`
(all-pods panic button) · `spend_ledger.py` (cap $120).
