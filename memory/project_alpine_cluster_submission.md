---
name: alpine-cluster-submission
description: Multiphase plan — one-click submit of NADOC MD jobs to CURC Alpine (SSH+SLURM); auto-resource decision tree with review; per-phase handoff
metadata: 
  node_type: memory
  type: project
  originSessionId: 909b50d7-8696-47a9-979c-fb67ba2f41ec
---

Add a remote execution backend so a prepared NADOC MD (NAMD) job can be submitted
to the **CU Research Computing "Alpine" cluster** (SLURM scheduler) with a
connect-once / submit flow, instead of only running as a local subprocess.
Design synthesized from the **NAMDRunner** reference project
(github.com/travisformayor/NAMDRunner — a Rust/Tauri app that already solved the
CURC/Alpine SSH→SLURM pipeline for the *same* DNA-origami CPD use case).

**Nothing lifts as code** (NAMDRunner is Rust; NADOC is Python/FastAPI + vanilla
JS). What transfers is the lifecycle design, the CURC/Alpine specifics, and two
pieces of portable *data* — all captured in the Appendix below so the reference
clone is not needed.

Related: [[md-job-system]] (the local job system this extends), [[md-prep-relaxation-exp29]]
(prep ladder that produces the package we ship), [[namd-solvate]], [[btube-benchmark]].

---

## HANDOFF — how to use this file

Each phase is a self-contained fresh-session chunk. To run one: open this file,
find the **first unchecked phase** in the Status tracker, read that phase's
section + the Appendix, implement, verify per its Done criteria, then **tick the
box and append a one-line "shipped:" note under that phase** before ending the
session. The user starts each with *"proceed to next phase of the alpine cluster md"*.

**Standing rules for every phase** (from `CLAUDE.md`):
- Backend change → run `just test`, cite pass count. Flag any test-count drop.
- Frontend change → exercise in the running app, or lead with `NOT VERIFIED IN APP`.
- **Module-first law.** New cohesive logic lands in the **new modules named per
  phase**, NOT in `main.js` or as a fat block in an existing file. `main.js` gets
  only import + factory init + thin wiring; cite its LOC Δ (flat/lower).
- New pure functions get ≥1 vitest/pytest test (input→output).

**External dependency:** Phases 1, 3, 4 need **real Alpine credentials + the user
present for Duo 2FA** to validate end-to-end. Auth cannot be fully headless
(see Appendix "Auth reality"). Schedule those validations when the user is available.

---

## Status tracker

- [x] **Phase 1** — Cluster config + SSH transport + connect UI (de-risk Duo auth)
- [x] **Phase 2** — SLURM script generation + auto-resource decision tree (pure logic)
- [x] **Phase 3** — Remote executor: submit / poll / fetch / cancel (wire it together)
- [x] **Phase 4** — Frontend: run-target selector + auto-with-review card + remote monitoring
- [x] **Phase 5** — Hardening: learned ns/day ✓, session-expiry UX ✓, live progress ✓ (increment 9);
  auto-resubmit → **user-driven one-click Resume from mid-segment checkpoint** ✓ (increment 10). See
  the "Resume model (2026-07-03 pivot)" block below before touching resume logic. Live-validation of
  the actual Resume round-trip still needs a real short-walltime timeout + Duo.
- [x] **Ensemble production replicas** (2026-07-07) — see "Ensemble production" block below.
- [x] **In-sbatch relaxation early-stop (Tier B + Tier A)** (2026-07-07) — see "In-sbatch early-stop" block below.

## In-sbatch relaxation early-stop / cutoff acceleration — 2026-07-07 (Tier B + Tier A shipped)

Port the local `early_stop_relax` accelerator ([[md-job-system]] "Relaxation early-stop
accelerator") to a whole-ladder Alpine sbatch, so a submitted relaxation **self-truncates
on the node with NO Python runner in the loop**. Purpose: fire off ~10 unattended CPU
relaxations for different designs (locally you can only run one GPU relaxation at a time).

**How it works (the node does what the local runner does, in bash):** after each conf,
the sbatch already has an idempotent `if [ -f output/<conf>.coor ]; then skip; else run; fi`
guard. Early-stop inserts, after each **non-final chunk of a well-restrained relaxation
stage**, an *evaluate-then-bridge* block: run a staged `python3 nadoc_cutoff_eval.py --log
output/<conf>.log`; on exit 0 (plateau), `cp` that chunk's final `{coor,vel,xsc}` onto
EVERY remaining chunk's expected names — both plain `<name>.<ext>` and `.restart.<ext>` —
exactly like `namd_runner._alias_skipped_stage_outputs`. The existing per-conf `.coor`
guards then no-op the bridged runs, and the next stage's first conf (which reads the
stage's LAST chunk by relative path) finds its checkpoint. Names are listed explicitly
(never globbed, full `_pNN` suffix) so `_p50`/`_p100` can't collide (ensemble revert-glob
lesson).

**New module `backend/core/remote_cutoff_eval.py`** — the node-side evaluator. **STDLIB-ONLY**
(a copy is staged and run on a bare node with no NADOC on `sys.path`): VENDORS
`md_cutoff.{CutoffParams,_series_flat,energy_plateaued,wc_plateaued,should_early_stop_stage}`
+ `namd_metrics.parse_namd_log_frames` verbatim. `tests/test_remote_cutoff_eval.py` pins the
copies stay in LOCKSTEP (same thresholds, same decisions on synthesized frames + the exp36
bank + real `workspace/md_jobs` logs, same parse on real log text) and the exit-code contract:
**0 = plateau (skip), 1 = hold, 2 = insufficient/error (fail-safe = run)**. Tier B (default)
= energy(+volume) only; `--wc <json>` gives Tier A (energy AND WC = `should_early_stop_stage`).

**Tier A (WC-gated, full local parity) — shipped 2026-07-07:** the on-node WC health step is
now wired. **New `backend/core/remote_health_eval.py`** (`nadoc_health_eval.py` on the node):
imports a STAGED verbatim copy of `md_health.py` (falls back to `backend.core.md_health` in-
repo), runs the REAL `run_health_check(package_dir, seg, stem)` on the chunk's `output/<seg>.dcd`
(reads only the staged PSF/PDB + DCD — its one `backend` import is declash-only + try-guarded,
so a non-declash design needs only numpy/scipy/MDAnalysis), and writes the chunk's `wc_per_frame`
to `output/<conf>.wc.json`. The sbatch (tier A) emits: run health (`|| true`, best-effort) →
`if [ -f wc.json ] && python3 nadoc_cutoff_eval.py --log <conf>.log --wc wc.json; then bridge`.
**Fails SAFE:** missing MDAnalysis / no frames / read error → no `wc.json` → gate falls through
to HOLD (Tier A never skips on energy alone). Tier A eligibility drops the k-gate (the WC series
holds fragile/low-k stages directly), so it considers EVERY non-final relaxation chunk incl.
k=0.01 and the k=0/MGHH melt — matching the local path (~60–70% skip on over-provisioned ladders).
**node-cwd log path:** the sbatch redirects each conf to `<conf>.log` in the run cwd (NOT
`output/`), coords/DCD go to `output/` — the early-stop guard/evaluator read `<conf>.log`
accordingly (fixed a first-cut bug where it read `output/<conf>.log` and never fired).
`early_stop_health_python` manifest override points the health step at a specific MDAnalysis
interpreter (default `python3`). `MdJob.early_stop_tier` ("B"|"A", default B, load-setdefault) +
`CreateJobRequest.early_stop_tier` select it; executor writes it into the (in-memory) manifest
before `generate_sbatch` and stages `nadoc_health_eval.py`+`md_health.py` when A. **OFFLINE-
VALIDATED end-to-end (minus the cluster):** `tests/test_remote_health_eval.py` runs the real node
path against a real 2hb_noT chunk DCD (MDAnalysis IS in the dev env) — produces a `wc.json`
byte-matching `run_health_check.wc_per_frame`, fed through the stdlib cutoff gate.

**`slurm_script.generate_sbatch`** — new `early_stop_relax: bool|None=None` param (None →
`manifest['early_stop_relax']`, absent → OFF → **byte-identical to before**, pinned). Pure
helpers `_stage_base`/`_is_production_segment`/`_stage_last_chunk_index`/`_chain_scales`
mirror the runner's (regex must stay identical). Eligibility (Tier B): non-min, non-
production/qualification, NOT the stage's last chunk, and **ENM `scale` (k) is not None AND
≥ `early_stop_min_k` (default 0.1)** — so k=0.5 & k=0.1 stages skip their p50/p100, but
**k=0.01 and the k=0/MGHH melt (scale None) always run in full** (energy-alone is unsafe at
low restraint — md_cutoff notes; 2hb_noT k=0.01). `early_stop_tier="A"` → `ValueError` (not
wired). `early_stop_min_k` tunable via manifest.

**Threading (`md_executor.py`):** `_early_stop_on(job,manifest)` = `job.early_stop_relax and
not manifest['declash']`; `submit_job`/`resume_job` pass `early_stop_relax=` to
`generate_sbatch` and `_stage_early_stop_evaluator` uploads the exact source of
`remote_cutoff_eval` as `nadoc_cutoff_eval.py` (into project→mirrored to scratch on submit;
straight to scratch on resume). `MdJob.early_stop_relax` already existed + is set at create
regardless of target.

**Coverage vs the local path:** Tier B conservatively skips the two well-restrained stages'
tails (~4 of ~12 chunks ≈ ⅓ of the canonical 4-stage ladder). Tier A adds the WC guard →
full local parity (~60–70%, incl. k=0.01/MGHH). Use B when unsure MDAnalysis is on the node
(it degrades to no-skip); A once the node python is confirmed to import MDAnalysis.

**DECLASH DEPENDENCY (out of scope, unchanged):** `generate_sbatch` still RAISES on a declash
manifest (mid-chain `rebuild_declashed_references` can't run in a bare sbatch). Early-stop is
a clean no-op there (`_early_stop_on` returns False AND the declash guard fires first).
Remote relaxation of extra-base designs (e.g. 6hbx100_1xT) is blocked independently. Validate
early-stop on a NON-declash design.

**Tests:** `tests/test_remote_cutoff_eval.py` (14 — parity/replay/exit-codes/standalone-run/
no-backend-import), `tests/test_remote_health_eval.py` (3 — real-DCD wc.json parity, missing-DCD
fail-safe, backend fallback), `tests/test_slurm_script.py` +~16 early-stop (off=byte-identical,
param>manifest, non-final-restrained-only, dot-safe bridge, never-production, min_k widening,
invalid-tier reject, declash-still-rejected, run-guards-intact; **Tier A**: health+wc gate emitted,
low-k/MGHH eligible, health_python override, tier-B emits no health), `tests/test_md_executor.py`
+4 (off=no staging, B=stdlib only, A=stages health+md_health). `bash -n` clean on B and A scripts.
**main.js Δ = 0 (backend-only).**

**LIVE VALIDATION 2026-07-08 — pipeline PROVEN, node-python BLOCKER found (fail-safe held):**
submitted a Tier-A early-stop 2hb_noT relaxation to Alpine — job `93592ef8d9e9`, **SLURM 29736115**,
amilan/32c/qos normal/2h walltime, via curl against the running backend (isolated `X-NADOC-Doc:
es-validate` doc so the browser session was untouched). **Confirmed live end-to-end:** prep→stage→
sbatch accepted→ran on amilan node c3cpu-c15-u9-4; the ladder ran `min→p10→p50→p100`; the node
**invoked `nadoc_health_eval.py` at exactly the right points** (after p10 AND p50 — the two non-final
k=0.5 chunks); p10 correctly held (13 frames < min_frames=20 → insufficient → defer to p50, matching
local calibration).
- **BLOCKER (fix owed):** the `.err` shows `nadoc_health_eval.py line 21: SyntaxError: future feature
  annotations is not defined` — amilan's default `python3` (after `module purge`; `/usr/bin/python3`
  ~3.6, node c3cpu) is **older than 3.7**, so `from __future__ import annotations` won't parse. Health
  crashed → no `wc.json` → Tier A gate held → **ladder ran full with NO corrupt skip (fail-safe worked
  exactly as designed).** The SAME `from __future__` line is in `remote_cutoff_eval.py` (line 30), so
  **Tier B would break identically on this node.** So neither tier can skip on Alpine as shipped.
- **FIX:** make BOTH node scripts parse+run on Python 3.6 — drop `from __future__ import annotations`
  and stringify/remove runtime-evaluated `list[...]`/`X|Y` annotations. Then **Tier B works on the bare
  node python3**; Tier A's cutoff-eval too, and only the WC **health** step needs a modern python (for
  MDAnalysis) via `early_stop_health_python`/a `module load python`. (Offline tests run on 3.12 so they
  DID NOT catch this — add an `ast`/`py_compile`-with-3.6-feature guard on the node scripts.)
- **Recovery lesson:** a user `/stop` (scancel + `apply_user_stop`) does NOT fetch outputs, and
  `poll_remote_jobs` skips stopped jobs → the `.out`/`.err` were stranded on scratch. Recovered with
  ZERO SU by editing job.json `status→running` so the 30 s supervisor reconciled it → `poll_status`
  saw SLURM CANCELLED → terminal → `fetch_outputs` pulled the scratch files → re-settled to stopped.
  (Better: let a validation run TIME OUT naturally, which fetches; or add a manual-fetch endpoint.)
- Everything else (submission, staging, sbatch acceptance, correct per-chunk invocation, fail-safe)
  is now LIVE-PROVEN. A successful SKIP still needs a re-run AFTER the node-python fix is staged.

**2nd live run (Tier B, job `069229d580f9`, SLURM 29739270) + node = Python 3.6 confirmed:** after
the `__future__` fix, the node got PAST that and hit `ModuleNotFoundError: No module named
'dataclasses'` (3.7+) — so **amilan's bare node `python3` is 3.6**. Fail-safe held again (ladder ran
min→p10→p50→p100, no corrupt skip). **FIX #2:** replaced the `@dataclass CutoffParams` in
`remote_cutoff_eval.py` with a plain class (class-level attrs) — `dataclasses` was the LAST 3.7+
feature; audited the rest (statistics/argparse/json/f-strings all 3.6-safe). Guard test extended to
reject any 3.7+ stdlib import at module scope (`PY37_PLUS` denylist). `md_health.py` (Tier A) is NOT
made 3.6-safe on purpose — Tier A needs a MODERN python for MDAnalysis anyway (`early_stop_health_python`).
- **DEFINITIVE (ran the FIXED evaluator on the REAL fetched cluster logs):** p10 → 13 frames < 20 →
  insufficient → hold (correct); **p50 → 51 frames, `energy_plateaued=False` → HOLD** because the
  POTENTIAL mean is still DRIFTING **+0.12%/window (+2.3% over the chunk)** — 2hb_noT (small, floppy,
  unsequenced) genuinely hasn't equilibrated by k=0.5 p50. So the live no-skip was the CORRECT decision
  once the crash is removed, NOT a bug.
- **Feature demonstrably skips (offline, on 4 REAL exp36 reference runs):** Tier-B energy-plateau would
  skip **18hb 8/8, 3x4SQ 26/30, 2hb 5/8, 3x6x200 4/8** non-final chunks. So the gate works; 2hb's live
  k=0.5 p50 just hit a slow trajectory. To WITNESS the live bridge-cp+jump, re-run a stiff design (18hb
  = 8/8) — bigger/more-SU; the mechanic itself is offline unit-tested + `bash -n` clean.
- **VALIDATION VERDICT:** pipeline + staging + sbatch-accept + correct per-chunk invocation + fail-safe
  (×2) + the 3.6-fixed evaluator making CORRECT decisions on real cluster data = ALL PROVEN. Only the
  cp+jump firing on the cluster is unwitnessed live (design-dependent; offline-proven). Node python = 3.6.
- **FIX APPLIED 2026-07-08:** removed `from __future__ import annotations` from BOTH
  `remote_cutoff_eval.py` (line 30) and `remote_health_eval.py` (line 21) — the only <3.7 blocker
  (all remaining new-generic annotations are function-LOCAL vars, which Python never evaluates).
  Now Tier B runs on Alpine's bare node `python3`; Tier A's cutoff too (health/MDAnalysis still needs
  a modern python via `early_stop_health_python` + `module load`, unbuilt). Regression guard
  `test_node_scripts_are_old_python_safe` (AST: no `__future__` ImportFrom, no EVALUATED
  list[]/dict[]/X|Y annotations in signatures or module/class scope, `py_compile` clean) — the offline
  suite runs on 3.12 so it could NOT catch this; the AST guard does. **Backend edit reloaded uvicorn →
  dropped the live Duo session** (expected). **OWED: reconnect + re-submit a short Tier B 2hb_noT run to
  witness an actual skip** (p10 holds on frames<20; p50 completes → energy plateau → bridges p100 →
  seg2 flips done + jumps to seg3/k=0.1 — observable via segment progress, no fetch needed).

**OWED — LIVE VALIDATION (needs Duo):** submit ONE real NON-declash relaxation to Alpine with
early-stop ON (set `#md-jobs-early-stop` before Relax→Alpine). Tier B: confirm the node skips
chunks (`.out` shows `[NADOC] early-stop: … plateaued — bridging N`), the ladder completes, the
skipped-endpoint structure ≈ a full run's endpoint, and `python3` (system, stdlib) is on PATH
after `module purge`/`module load namd`. **Tier A additionally:** confirm the node python imports
MDAnalysis (else it silently degrades to no-skip — check `.out` for `[nadoc-health]` errors); a
quick pre-check is `md_executor` / a manual remote `python3 -c "import MDAnalysis"`; set
`early_stop_health_python`/the right `module load` if the default `python3` lacks it. Log an MV
row. Same owed live check as the local path's (never exercised on a live GPU relax either).

## Ensemble production (multi-seed replicas on amilan) — 2026-07-07

Fan out **N independent NAMD production replicas** (distinct seeds) from ONE equilibrated
structure across Alpine's free CPU cores. Model: the completed relaxation is the PARENT
`MdJob`; each replica is a child (`parent_job_id` set, `execution_target="alpine"`,
`ensemble_seed`/`ensemble_index`) with its own production-only package, its own sbatch →
own `slurm_job_id`, polled independently by the existing `poll_remote_jobs` loop. Reuses
the whole per-job remote infra unchanged. Confirmed decisions: relax-once→N-production
(not N full runs); N separate sbatch (not a job array); auto-generated distinct seeds
(`base+i`); default **amilan CPU**; independence via **reinitvels** (same equilibrated
coords, fresh MB velocities per seed).

- **Flexibility-map fix (2026-07-09)**: a replica production package must ALSO carry
  `charge_audit.json` (the segid→NADOC-chain map). `build_replica_package` originally
  hardlinked only PSF/PDB/forcefield/hmr, so `load_segid_chain_map` fell back to the
  reference-PDB P-order — which can't build the 21 phosphate-less 5'-termini specs → those
  bases rendered un-positioned/un-coloured in the Flexibility map (RMSF returned 1307/1328
  keys). Fix = two layers: (A) `build_replica_package` now `_link_or_copy`s
  `charge_audit.json`; (B) `load_segid_chain_map` falls back to `manifest.json`'s embedded
  `charge_audit` field when the standalone file is absent (fixes replicas already on disk —
  the child manifest already carries the map). Verified on prod job `6d7c2e38e455`: RMSF
  route now returns 1328/1328. See LESSONS A10.
- **New module `backend/core/md_ensemble.py`**: `generate_seeds`, `build_replica_package`
  (production-only child pkg: hardlinks parent PSF/PDB/forcefield/hmr; copies the parent's
  `_production_ready_checkpoint` `output/{ready}.{coor,xsc}` → package-root
  `equilibrated.{coor,xsc}` so `stage_plan` uploads them; writes a **reseed** conf
  [manifest `minimization` slot: reads root equilibrated coords, `reinitvels 300` from the
  seed, `run 0` → writes `output/{reseed}.{coor,vel,xsc}`] + a **production** conf reading
  that; manifest is production-only, NO `declash` key, `total_ns == length_ns`).
- **`md_protocols.build_production_conf`** (+`build_reseed_conf`) — the production conf
  template MOVED out of `routes_md._conservative_production_conf` (now a thin delegate,
  byte-identical by test) so it's parameterized by `seed` + `start_checkpoint` and callable
  from the ensemble module without a circular import.
- **Endpoints** (`routes_md.py`): `POST /md/jobs/{parent}/ensemble-production` (offline —
  stage N prepared replica children; validates parent completed + production-ready) and
  `POST /md/jobs/{parent}/ensemble-submit` (live — sizes amilan resources ONCE, loops
  `md_executor.submit_job` over the replicas; one failure doesn't abort the rest).
- **`MdJob`** +`ensemble_seed`/`ensemble_index` (setdefaults + new_job kwargs).
- **Frontend**: `job_tree.flattenJobTree(jobs,{collapsedIds})` gains `childCount` + subtree
  hiding; `md_jobs_panel` gets an expand/collapse chevron (ensemble parents **default
  collapsed** → one expandable item), `ensembleChildSummary`/`mdReplicaRowLabel`/
  `mdIsEnsembleParent`/`mdIsEnsembleReplica` pure helpers, and a **☁ Ensemble on Alpine**
  detail control (count input; shown for a completed non-replica job, disabled+tooltip until
  connected) that stages then opens `md_submit_review` in **`mode:'ensemble'`** (sizes a
  replica child on amilan, button "Submit N replicas" → `submitMdEnsemble`). `main.js` Δ = 0.
- Tests: `tests/test_md_ensemble.py` (13, incl. conf byte-parity delegate proof),
  `job_tree.test.js` + `md_jobs_panel.test.js` ensemble helpers. `just test` green (the 2
  `test_remote_recommendation_*` fails are PRE-EXISTING flaky xdist-isolation on clean
  master — verified by stashing). `just test-frontend` 2295, `just smoke` 23 (0 console err).
- **Offline-verified live vs real data** (job `acc229c76c42`, 2hb): staged 2 replicas →
  distinct seeds 54321/54322, correct reseed+production confs + equilibrated coords at root,
  amilan recommendation (31790 atoms / cpu / 32 core / normal qos), parent lists 2 replica
  children; test children then deleted. **NOT live-validated on Alpine** — the actual
  ensemble-submit round-trip (N sbatch, per-replica SLURM tracking) needs the user + Duo;
  scheduled for the user's next connect. Gate note: the **☁ Ensemble** button is disabled
  while disconnected (staging is offline-capable but currently gated on connection to match
  the single-job Alpine flow) — revisit if offline staging is wanted.

---

## Key architecture decisions (read before Phase 1)

1. **Whole-ladder single sbatch, NOT per-segment submission.** The remote job is
   ONE `sbatch` script that runs the entire segment chain (minimize → all
   ENM-release segments → optional production) on the compute node, exactly like
   NAMDRunner. NADOC polls `squeue`/`sacct` for status and fetches outputs.
   - *Why not per-segment?* NADOC's local runner orchestrates one segment at a
     time (health check between). Re-queuing each segment on a scheduler stacks
     hours of queue latency per segment — unacceptable. A single job avoids that.
   - *What we lose:* between-segment control flow. **Nothing, in practice** — the
     health gate is already **advisory-only** (removed as control flow 2026-06-25,
     see [[md-job-system]]). Health is display metadata, computed *after* fetching
     `health.jsonl`/restart coords back to the login node / locally. So a single
     remote job loses no behavior we still rely on.

2. **Local execution path stays byte-for-byte unchanged.** We do NOT rewrite
   `run_job`/`_run_namd_async`. The seam is a **branch at `start_job` / `stop_job`
   / `reconcile_job_status` on a new `MdJob.execution_target` field** (`"local"`
   default vs `"alpine"`). All remote logic lives in new modules. This is the
   low-risk seam the repo philosophy wants ("modify existing > new module > never
   a fat block"), not a deep executor rewrite.

3. **GPU by default.** NADOC's local pipeline is CUDA and NAMD3 GPU-resident is
   far faster; target Alpine's `aa100` (A100) partition + a GPU NAMD module by
   default, CPU (`amilan`) only as fallback. (NAMDRunner used the CPU build — we
   diverge here deliberately.)

4. **Credentials live in backend memory only, never on disk.** Password + Duo held
   for the session; on expiry the UI shows "Reconnect". No key files (CURC
   disables SSH keys — see Appendix).

---

## Phase 1 — Cluster config + SSH transport + connect UI

**Goal:** Prove the riskiest unknown first — that we can authenticate to Alpine
(password + Duo), run a remote command, and round-trip a file. Ship the config
model + connection UI around it.

**New modules:**
- `backend/core/cluster_config.py` — `ClusterProfile` dataclass (host, scheduler,
  project/scratch base paths, module loads, default partition/QoS) + the embedded
  **Alpine profile** (Appendix data). Loaded from a `workspace/clusters.json` (or
  defaults if absent). NO credentials here.
- `backend/core/cluster_ssh.py` — `asyncssh`-based connection manager (async-native,
  fits FastAPI; alternative `paramiko`+`fabric` if asyncssh fights Duo). Singleton
  per session holding one live connection. Methods: `connect(host, user, password,
  duo_method)` (keyboard-interactive), `run(cmd, timeout)` → (rc, stdout, stderr),
  `sftp_put`/`sftp_get` (chunked, 256 KB, per-chunk timeout — see Appendix),
  `mirror(src, dst)` (rsync-over-ssh or sftp walk), `disconnect()` (clears creds).
  Connection state enum: Disconnected/Connecting/Connected/Expired.
- `backend/api/routes_cluster.py` — `POST /api/cluster/connect`, `GET
  /api/cluster/status`, `POST /api/cluster/disconnect`. (New router; register in
  `main.py` like other routes — thin.)
- `frontend/src/ui/cluster_connection.js` — `initClusterConnection({deps})→{api}`:
  the status chip (grey/amber/green/amber-expired) + connect modal (host prefilled
  `login.rc.colorado.edu`, user, password, Duo Push/passcode). `main.js` gets
  import + init + one wiring line only.

**Done criteria:**
- `just test` green (+ new `tests/test_cluster_config.py`, `test_cluster_ssh.py`
  with a mocked transport — no real network in the suite).
- **Live validation (needs user + Duo):** connect to real Alpine, `GET
  /api/cluster/status` shows `connected jojo@login.rc.colorado.edu`, a manual
  `whoami` round-trips, and one small file uploads + downloads intact.
- Connect chip exercised in app; cite `main.js` LOC Δ.

*shipped:* 2026-07-03. Modules: `backend/core/cluster_config.py` (`ClusterProfile`
+embedded Alpine profile, `load_profiles`/`resolve_paths`/`profile_with_gpu_modules`),
`backend/core/cluster_ssh.py` (`ClusterConnection` singleton, injectable `connector`
for tests, state machine DISCONNECTED→CONNECTING→CONNECTED/EXPIRED, keyboard-int Duo
handler, chunked sftp put/get + rsync mirror, creds never retained/logged),
`backend/api/routes_cluster.py` (`GET /cluster/{profiles,status}`, `POST
/cluster/{connect,disconnect}` — mounted in main.py; distinct from plural
`routes_clusters.py`=deformation clusters), `frontend/src/ui/cluster_connection.js`
(`initClusterConnection({mount,fetchImpl})→{refresh,getState,dispose}`; chip+modal;
pure `chipStyleForState`/`whoLabel`/`connectPayload`). Dep added: `asyncssh` (lazy-
imported so absence doesn't break import). Tests: `tests/test_cluster_config.py` (10),
`tests/test_cluster_ssh.py` (11, fake connector — no network), `cluster_connection.test.js`
(10). `just test` 3660 passed (1 pre-existing FAIL `test_duplex_geometry` = hardcoded
`/home/joshua/…` fixture from other computer, unrelated). App-exercised: chip renders
"Disconnected", modal opens w/ host prefilled from `/cluster/profiles`, empty-submit
validation, cancel closes, zero console errors. **main.js Δ = +3 lines pure wiring**
(1 import + 1 comment + 1 init call). **NOT live-validated against real Alpine** —
needs user present for Duo (Phase 1 external-dep caveat); the auth handshake path
(`_asyncssh_connect` keyboard-interactive Duo answers) is the one untested-live piece.

**USER TODO (live Duo validation, needs you present):**
1. Start backend+frontend, expand the Molecular Dynamics panel, click the grey
   "Cluster: Disconnected" chip.
2. Enter your CU IdentiKey user + password, leave Duo as "push" (or type a passcode),
   click Connect, approve the Duo push on your phone.
3. Confirm the chip turns green "Cluster: jojo@login.rc.colorado.edu" and
   `GET /api/cluster/status` shows `connected`. Then a manual round-trip check:
   the Phase-3 executor will exercise `run`/`sftp` — for now just confirm connect works.
   If the keyboard-interactive prompt order differs from the assumed
   password-then-Duo, adjust `_kbdint_answers` in `cluster_ssh.py`.

*fix 2026-07-03 (live-connect bug):* first real connect attempt failed with
`SSHClientConnectionOptions.prepare() got an unexpected keyword argument
'kbdint_challenge_handler'` — asyncssh 2.24 has no such kwarg. Keyboard-interactive
is driven by `SSHClient` **callbacks**, not a handler kwarg. `_asyncssh_connect` now
passes a one-off `SSHClient` subclass via `client_factory=` whose
`kbdint_challenge_received` calls the extracted pure `_kbdint_answers(password,
duo_method, prompts)`. Added `test_asyncssh_connect_kwargs_are_valid` (constructs the
options asyncssh builds, so a bad kwarg fails in-suite next time) + 4 `_kbdint_answers`
tests. Still needs live Duo validation.

---

## Phase 2 — SLURM script generation + auto-resource decision tree

**Goal:** Pure, offline, heavily-tested logic — from a prepared job's manifest,
produce (a) a valid Alpine `sbatch` script and (b) an auto-resource recommendation.
No network; no execution. This is the safest phase and can be done anytime.

**New modules:**
- `backend/core/slurm_script.py` — `generate_sbatch(job, resources, remote_paths)`.
  Ports the Alpine recipe (Appendix): `#SBATCH` directives, `module load` block,
  GPU vs CPU exec line (`namd3 ... +devices` for GPU-resident; `mpirun -np
  $SLURM_NTASKS namd3` for CPU), the segment-chain loop that mirrors NADOC's
  ladder (minimize.conf → each segment .conf → production). Sanitize job name;
  reject empty. Pure function → unit tests assert directives/modules/exec line.
- `backend/core/cluster_resources.py` — the **auto-with-review decision tree**:
  - Inputs already available post-prep: total atoms (PSF `!NATOM` / solvated PDB),
    box dims + segment count + steps + timestep (manifest → total ns), and
    **measured ns/day** (NADOC's `metrics.jsonl` already records it).
  - `recommend(job) → {partition, gpus, cores, mem_gb, walltime, qos,
    est_queue, est_cost_su, safety_factor, notes}`.
  - Rules: default GPU `aa100`; CPU `amilan` only if too big for one GPU.
    `walltime = total_ns / expected_ns_per_day × safety_factor`, clamp to QoS
    ceiling (24 h `normal`, 168 h `long`); auto-bump `normal`→`long` near the
    boundary rather than truncate. mem from atom count + headroom. cores modest
    for GPU-resident.
  - `estimate_queue_time` + `estimate_cost_su` ported directly from NAMDRunner
    logic + the Appendix billing table.

**Done criteria:**
- `just test` green (+ `tests/test_slurm_script.py`, `tests/test_cluster_resources.py`
  — table-driven: small/large × short/long → expected partition/QoS/walltime bucket).
- Generate a sbatch for a real prepared job dir and eyeball it against the Appendix
  recipe. No app exercise needed (pure backend).

*shipped:* 2026-07-03. Two new pure/offline modules:
- `backend/core/slurm_script.py` — `generate_sbatch(manifest, profile, resources,
  remote_scratch_dir, *, job_name=None)` builds the sbatch string. Key insight: the
  prepared package **already has every `.conf` on disk** (one `*_00_min*.conf` +
  one per relax segment, each reading the previous segment's restart coords by
  relative path — confirmed against `workspace/md_jobs/03302b74a7fa`). So the script
  is just `cd <scratch>` → run min → run each segment conf in manifest order,
  redirect each to `<conf>.log`. No between-segment Python (health is advisory,
  recomputed locally post-fetch — plan decision #1). GPU exec = `namd3 +p<cores>
  +setcpuaffinity +devices 0[,…] <conf>.conf`; CPU exec = `mpirun -np $SLURM_NTASKS
  namd3 …` (partition `kind` from the profile picks which). Helpers `sanitize_job_name`
  (SLURM-safe, rejects empty), `_segment_chain`, `_sbatch_directives`, `_module_block`,
  `_exec_line`. **Guards:** declash manifest → `ValueError` (needs a mid-chain
  `rebuild_declashed_references` Python step that can't run in a bare sbatch — run
  those locally / stage later); unknown partition → `ValueError`; no segments →
  `ValueError`. **Honesty warning:** GPU partition + a `*_cpu` module in the profile
  emits a loud `# WARNING … CPU-only` comment (the embedded Alpine profile ships
  `namd/3.0.1_cpu` by default — the real GPU NAMD module name is TBD, confirm live
  and set in `workspace/clusters.json`).
- `backend/core/cluster_resources.py` — `recommend(profile, *, n_atoms, total_ns,
  measured_ns_per_day=None, safety_factor=1.5) → {partition, kind, gpus, cores,
  mem_gb, walltime, walltime_h, qos, expected_ns_per_day, measured, est_queue_min,
  est_cost_su, safety_factor, notes}`. GPU-first (`aa100`, 1 GPU, 8 cores); CPU
  `amilan` fallback only above `_GPU_ATOM_CEILING`=3M atoms. `walltime = total_ns /
  expected_nsday × 24 × safety`, clamp to QoS ceiling, auto-bump normal(24h)→long(168h)
  rather than truncate; clamp warns about needing Phase-5 auto-resubmit. Throughput
  guess `_gpu_nsday_guess ≈ 2.9e6/n_atoms` (anchored to ~180k→16 ns/day; a first-run
  guess, Phase 5 learns real values); CPU guess ×0.15. `est_cost_su = cores·h·1.0 +
  gpus·h·108.2`. Thin extractors: `n_atoms_from_manifest` (charge_audit
  final_solvated→dry fallback), `total_ns_from_manifest` (Σ segment steps × ts_fs,
  min excluded, + production_extension), `latest_ns_per_day(metrics.jsonl)`.
- Eyeballed against real `03302b74a7fa` manifest (178,518 atoms, 19.2 ns): recommend
  gave aa100/1gpu/8core/19GB/42.5h→`long`/4944 SU; generated sbatch matched the
  Appendix recipe (13 confs in order). Tests: `tests/test_slurm_script.py` (15),
  `tests/test_cluster_resources.py` (16). `just test` = **3696 passed**, 106 skipped,
  1 xfailed; the lone FAIL `test_duplex_geometry::…flip…2x2` is the same pre-existing
  hardcoded `/home/joshua/…playwright_tests/2x2_OH_test.nadoc` fixture from the other
  computer (unrelated — also failed in Phase 1). Pure backend — no app exercise, no
  `main.js` touch.

---

## Phase 3 — Remote executor: submit / poll / fetch / cancel

**Goal:** Wire Phases 1+2 into the job lifecycle. Submit a real job to Alpine and
watch it run to completion with outputs landing locally.

**Changes:**
- `backend/core/md_job.py` — `MdJob` gains: `execution_target` ("local"|"alpine",
  default "local"), `cluster_name`, `slurm_job_id`, `remote_project_dir`,
  `remote_scratch_dir`, `resources` (the recommendation dict actually used).
  Load-setdefault for old jobs (they're all "local").
- `backend/core/md_executor.py` (new) — `SlurmExecutor`:
  1. stage prepared package → `remote_project_dir` (sftp, chunked);
  2. `mirror` project→scratch (Alpine two-filesystem model, Appendix);
  3. write + upload the Phase-2 sbatch;
  4. `sbatch`, parse `Submitted batch job <id>` → `slurm_job_id`;
  5. poll `squeue -j … --format='%i|%T'` (active) then `sacct` (finished), map
     status codes (Appendix table);
  6. on completion `mirror` scratch→project, fetch outputs (logs, `metrics.jsonl`,
     restart/DCD) back locally so the existing detail view + health compute work;
  7. `scancel` for stop.
- `backend/core/namd_runner.py` — `start_job`/`stop_job`/`reconcile_job_status`
  **branch** on `execution_target`: "local" → existing path untouched; "alpine" →
  `SlurmExecutor`. The 30 s supervisor loop (`_md_supervisor_loop` in `main.py`)
  also polls remote jobs' status (respect a 30–60 s cache TTL — don't hammer the
  scheduler).
- `routes_md.py` — `CreateJobRequest`/start accept `execution_target` +
  `cluster_name` (optional; default local → zero behavior change).

**Done criteria:**
- `just test` green (executor unit-tested against a **mocked** `cluster_ssh`
  returning canned `sbatch`/`squeue`/`sacct` output — assert state transitions,
  id parsing, status mapping, no double-submit).
- **Live validation (needs user + Duo):** submit a small real design to Alpine,
  observe `queued→running→completed`, confirm outputs fetched locally and the
  existing job detail renders them. Watch scratch-purge timing.

*shipped:* 2026-07-03. New module `backend/core/md_executor.py` — the `SlurmExecutor`
as a set of **injectable-`conn` async functions** (not a class; tests pass a FakeConn,
no network). Pure parsers (unit-tested): `parse_sbatch_job_id`, `parse_state_lines`
(squeue `%i|%T` AND sacct `JobID|State`, handling `.batch` sub-step rows + `CANCELLED
by <uid>`), `map_slurm_state` (Appendix code→bucket; unknown→`running` so we keep
polling), `bucket_to_md_status`, `is_remote_active`, `stage_plan` (walk package_dir,
**skip `output/` tree + `*.log`** — a fresh remote run makes its own). Async orchestration
(runs on the main loop the asyncssh session is bound to): `submit_job` (resolve
project/scratch paths → generate sbatch FIRST so a declash/bad-partition raises pre-
network → sftp package to project → `mirror` project→scratch → upload+`sbatch` in
scratch → parse id; **idempotent** — a job with a `slurm_job_id` is not re-submitted),
`poll_status` (squeue→sacct fallback→absent=completed), `fetch_outputs` (mirror
scratch→project, then `find output -type f` + top-level `*.log`/`*.out`/`*.err` →
`sftp_get` each locally, best-effort per file), `cancel_job` (`scancel`),
`reconcile_remote_job` (poll→advance status; terminal→fetch+`_finalize_local_bookkeeping`
which recomputes metrics+health per completed segment from fetched logs/coords — the
between-segment bookkeeping a bare sbatch skips, plan decision #1), `poll_remote_jobs`
(supervisor pass; no-op when disconnected).

**Seam wired (local path byte-for-byte unchanged):**
- `MdJob` +fields `execution_target` ("local"|"alpine", default local), `cluster_name`,
  `slurm_job_id`, `slurm_state`, `remote_project_dir`, `remote_scratch_dir`, `resources`
  (+ load-setdefaults for old jobs).
- `namd_runner.py` branches: `start_job` no-ops for non-local; `reconcile_job_status`
  returns the job untouched for non-local (its status is driven by the poll pass, NOT
  local /proc reconcile — important, since `_load_job` reconciles on every endpoint hit);
  `resume_interrupted_jobs` skips non-local.
- `main.py` `_md_supervisor_loop` gained a second pass: `await poll_remote_jobs(ws)`
  (on the main loop = the connection's loop; guarded, logs touched jobs).
- `routes_md.py`: `CreateJobRequest` +`execution_target`/`cluster_name` (tags the job at
  prep; local autostart still launches, remote defers). New `POST /md/jobs/{id}/submit-remote`
  (needs a live session; auto-recommends resources from the prepared manifest via
  `cluster_resources.recommend` unless overridden → `md_executor.submit_job`). `stop_md_job`
  branches: remote → `await md_executor.cancel_job` (this endpoint runs on the connection's
  loop); disconnected → mark stopped locally, skip scancel.
- `slurm_script.generate_sbatch` now emits `mkdir -p output` after the `cd` (staging
  excludes the local `output/`, so the remote run needs to create it).

**Event-loop affinity (the key constraint):** the asyncssh connection is bound to the
main uvicorn loop (created in `/cluster/connect`). So ALL remote asyncssh ops run there —
via the async endpoints (`submit-remote`, `stop`) and the async supervisor. The **sync**
`namd_runner` seam never touches remote jobs (it would be on the wrong loop/thread); it
only guards them out. No `run_coroutine_threadsafe`, no remote thread.

Tests: `tests/test_md_executor.py` (20, FakeConn — parsers + submit/poll/reconcile/cancel/
supervisor state transitions + idempotent no-double-submit). `just test` = **3716 passed**
(+20 vs Phase 2's 3696), 106 skipped, 1 xfailed; lone FAIL is the same pre-existing
hardcoded `/home/joshua/…2x2_OH_test.nadoc` fixture from the other computer (unrelated —
also failed in Phases 1 & 2). Backend-only, **no frontend touched** (main.js Δ = 0 — that's
Phase 4). Sbatch eyeballed against real `03302b74a7fa` manifest: aa100/1gpu/8core/19GB/
42.5h→long, `mkdir -p output` present, 13 confs in order.

**NOT live-validated against real Alpine** — Phase 3 external-dep caveat (needs user + Duo).
The untested-live pieces: the real sftp package upload (multi-MB PSF), the project↔scratch
`rsync` on Alpine's two-filesystem model, actual `squeue`/`sacct` output formats, and
scratch-purge timing. Known edge: `poll_status` treats "absent from squeue AND sacct" as
completed — fine post-sbatch (the job is registered) but could misread a purged old job.

**USER TODO (live end-to-end, needs you present for Duo):**
1. Connect to Alpine (Phase 1 chip). Prepare a SMALL design's MD job.
2. `POST /api/md/jobs/{id}/submit-remote` (or curl) → confirm it returns a `slurm_job_id`
   and the job flips to `queued`. Watch the supervisor (≤30 s ticks) move it
   `queued→running→completed`, then confirm outputs (logs, restart, DCD) landed locally
   and the existing job detail view renders them.
3. If `squeue`/`sacct` column output differs from the assumed `%i|%T` / `JobID|State`
   parsing, adjust `parse_state_lines`. If the GPU NAMD module name matters, set it in
   `workspace/clusters.json` (the embedded profile ships `namd/3.0.1_cpu` + a loud sbatch
   WARNING).

---

## Phase 4 — Frontend: run-target selector + auto-with-review card

**Goal:** The user-facing one-click-after-review flow (decision confirmed:
**auto-with-review**, collapsible to one-click later).

**Changes:**
- `frontend/src/ui/md_submit_review.js` (new module) — the review card: shows
  system size / protocol / total ns, the auto-selected resources with an `[edit]`
  drawer (override partition/cores/walltime/QoS), est. queue + est. SU cost, and
  the walltime safety-margin note. `[Submit job]` posts with the chosen resources.
- `frontend/src/ui/md_jobs_panel.js` — a **Run on: (Local)(Alpine)** toggle by the
  existing Relax/Production buttons (Alpine disabled+tooltip unless connected);
  Alpine target opens the review card instead of launching immediately. Job list:
  remote badge (SLURM id + partition), status chips driven by backend poll (reuse
  existing chip code), remote log/metric display reuse the existing detail view.
- `main.js` — import + init the review module + one wiring line; cite LOC Δ.

**Done criteria:**
- `just test-frontend` green (+ vitest for the pure bits: resource-summary
  formatting, disabled-state logic, review→submit payload shape).
- `just smoke` (console-error gate) green.
- **Exercised in app** (needs a connected session for the full path): target
  toggle, review card renders auto-resources + edit, submit round-trips, remote
  job appears with badge and live chip. Lead with `NOT VERIFIED IN APP` if no
  live Alpine session was available and note which parts were mock-only.

*shipped:* 2026-07-03. New module `frontend/src/ui/md_submit_review.js` — the
auto-with-review submit card. Factory `initMdSubmitReview({api, onSubmitted, toast})
→ {open(jobId), dispose}`; `open` fetches `GET /md/jobs/{id}/remote-recommendation`
(read-only, no connection needed), renders a modal with system size / total ns /
partition / hardware / walltime / QoS / throughput / est. queue / est. SU cost +
recommendation notes, an [Edit resources] drawer (override partition/gpus/cores/
mem_gb/walltime/qos — blank = keep auto), and `[Submit job]` → `POST submit-remote`.
Pure helpers (unit-tested): `formatResourceSummary`, `reviewSubmitPayload` (blank
overrides ⇒ auto-recommend `{cluster_name}` only; edits ⇒ full merged `resources`
dict sent verbatim; numeric coercion for gpus/cores/mem_gb), `alpineTargetDisabledReason`,
`remoteJobBadge`, `fmtQueueMinutes`, `fmtNs`.

**Backend (thin):** new `GET /md/jobs/{id}/remote-recommendation?cluster_name=&safety_factor=`
returns `{prepared, n_atoms, total_ns, measured_ns_per_day, resources, already_submitted,
…}` — or `{prepared:false, reason}` while still preparing (NOT a 400, so the review card
can poll). Factored `_size_prepared_job(job, profile, safety_factor)` shared with the
Phase-3 submit path's `_remote_resources`.

**Panel wiring (`md_jobs_panel.js`):** new dep `getClusterState`; a **Run on: Local |
Alpine** radio pair by the Relax button (Alpine disabled + tooltip + `(connect cluster)`
hint unless connected — driven by the new `nadoc:cluster-state-change` event that
`cluster_connection.render()` now dispatches). Relax tags the create with
`execution_target`/`cluster_name`; for Alpine it sets `_pendingAlpineReview` and the
review card auto-opens once the job reaches `queued` (prepared) via `_maybeOpenAlpineReview`
in `_applyJobState`. A **☁ Submit to Alpine** detail button re-opens the card for a
prepared, not-yet-submitted remote job. List rows show a blue remote badge
(`remoteJobBadge` → `SLURM <id> · <partition>`, else `Alpine`); `mdListSignature` now
keys on `execution_target`/`slurm_job_id` so the badge refreshes on submit.

**main.js Δ = +3 lines pure wiring** (getClusterState arrow + comment + init reorder;
capture the `initClusterConnection` return). Tests: `md_submit_review.test.js` (17,
pure helpers), `tests/test_md_executor.py` +3 (endpoint prepared/unprepared/404).
`just test` = **3719 passed** (+3 vs Phase 3's 3716), 106 skipped, 1 xfailed; lone FAIL
= same pre-existing hardcoded `/home/joshua/…2x2_OH_test.nadoc` fixture (unrelated,
failed in Phases 1-3 too). `just test-frontend` = 1957 passed (23 pre-existing FAILs in
`oxdna_jobs_panel.test.js` = stale `vi.mock` missing `startOxdnaMetrics`, confirmed
pre-existing by stashing client.js — unrelated to this work). `just smoke` = 22 passed
(teardown-gate flaked on a scene-load timeout, passed on retry). **App-exercised
(live):** run-target toggle shows Alpine disabled + correct hint/tooltip while
disconnected; review card fetches the REAL recommendation for prepared job `03302b74a7fa`
and renders "178,518 atoms / 19.2 ns / aa100 (gpu) / 1 GPU·8 core / long / 3711 SU"
(measured 21.6 ns/day → bumped normal→long), zero console errors.

**NOT live-validated against real Alpine** (Phase 4 external-dep caveat): the actual
`submit-remote` round-trip through the review card's `[Submit job]` needs a live Duo
session (Phase 3's USER TODO covers the submit path itself). Everything up to the POST
is exercised; the POST handler is Phase-3-tested with a FakeConn.

**USER TODO (live, needs you present for Duo):**
1. Connect to Alpine (chip). In the MD panel pick **Run on: Alpine**, set a SMALL design,
   click Relax. Prep runs locally; the review card should auto-open once prepared.
2. Eyeball the auto-resources, optionally edit a field, click **Submit job** → confirm a
   `slurm_job_id` toast and the job row grows a blue `SLURM <id> · aa100` badge and moves
   `queued→running→completed` under the supervisor, with outputs fetched locally.
3. If anything in the card reads wrong (e.g. GPU module name), it flows from the Phase-2
   profile — set overrides in the Edit drawer or `workspace/clusters.json`.

*fix 2026-07-03 (live-submit bugs, found during first real Alpine submit):*
1. **Prep `_hmr.pdb` crash** — `prepare_mgh_slow_release` derived `name_stem` from an
   unsorted `glob("*.psf")[0]`, which intermittently picked the derived `{stem}_hmr.psf`
   → downstream opened a phantom `{stem}_hmr.pdb`. Fixed with `_base_name_stem()` (filters
   `*_hmr.psf`); same latent bug fixed in `benchmark_runner.py`. See [[LESSONS]] C9.
2. **GPU QoS names** — the embedded profile shipped only `normal`/`long`, but Alpine's
   aa100 requires `gpu-normal`/`gpu-long`/`gpu-testing` (SLURM rejects the plain names).
   Added the gpu-* tiers + `ClusterProfile.qos_for(kind, tier)`; `recommend()` now picks
   by partition kind. GPU ceilings assumed 24/168 h — confirm live.
4. **Failed-submit jobs looked like running jobs.** `submit_job` only persists on
   success, and the endpoint caught the exception without recording anything — so a
   rejected submit left the job a clean `queued` with no error, and the list row
   (`mdJobIsActive` treats `queued` as active) showed a running spinner. Fixes:
   backend `_record_submit_failure(job, msg)` sets `job.error` (keeps it `queued` =
   prepared/retryable, clears slurm id); frontend `mdRemoteAwaitingSubmit(job)`
   (alpine + queued + no slurm id) → `mdJobIsActive` returns false (no spinner) and
   the detail shows "Prepared — submit to Alpine" or the submit error + ☁ retry
   button. So an Alpine job only reads as "running" once it actually has a SLURM id.
5. **Typed GRES + no IB constraint (2nd/3rd live sbatch rejections).** aa100 rejects a
   bare `--gres=gpu:N` — it requires a TYPED GRES (`gpu:a100-40gb:N`; `a100_80gb` also
   valid). Added `Partition.gres_type` (aa100/atesting_a100=`a100-40gb`, ami100=`mi100`,
   al40=`l40` — only a100 live-confirmed), `recommend()` includes it, `_sbatch_directives`
   emits `gpu:<type>:N`. Also made `#SBATCH --constraint=ib` **CPU-only** — a single-node
   GPU-resident job doesn't need InfiniBand and it over-constrains aa100 node selection
   (would be the next "node configuration not available"). Live sbatch now:
   `--partition=aa100 --qos=gpu-long --gres=gpu:a100-40gb:1`, no IB constraint.
3. **Declash guard** — a design with extra bases at crossovers auto-enables declash, whose
   mid-chain `rebuild_declashed_references` (Python/MDAnalysis) can't run in a bare sbatch,
   so `generate_sbatch` refuses it. Not yet worked around; local-prestage (run min+rebuild
   locally, ship a segments-only sbatch) is the intended Phase-5 fix. User removed the
   extra bases to proceed. **The pipeline works end-to-end through sbatch submission** —
   staging, sftp upload, project→scratch mirror, and `sbatch` all succeeded live; only the
   QoS name was rejected (now fixed).

---

## Phase 5 — Hardening: learned ns/day, auto-resubmit, session-expiry UX

**Goal:** Make the auto-decision self-correct and make failure modes graceful.

### Resume model (2026-07-03 pivot — supersedes the auto-resubmit chain)

User directive after the first live TIMEOUT (job `2719c1c8700f`, SLURM 29566908→auto-resubmit→
29572963, then stopped): **do NOT auto-resubmit in the supervisor.** Rationale + the correct model:
- **Long walltimes get lower scheduler priority (esp. GPU).** A series of SHORT jobs finishes sooner
  than one long job. So the intended usage is: submit with a short walltime that WILL time out, then
  resume-from-checkpoint as a fresh submission — repeatedly — rather than request one 50 h block.
- **Duo 2FA blocks automation.** A resubmit needs a live SSH session, which needs the user present
  for Duo. So NADOC must NOT loop/auto-resubmit. Instead: a timed-out job enters a **resumable**
  state; the user logs in (Duo) and clicks **Resume** (one click) → NADOC resubmits from the latest
  checkpoint as a new SLURM job.
- **NADOC's job = prepare a job to be resumable, then one-click resume.** Because Resume is
  user-triggered with the **backend present**, NADOC can be smart at resume time (unlike a bare
  node): inspect scratch, find the interrupted segment + its restart step, generate the resume conf
  (reuse the local runner's `_write_resume_conf` logic), upload a resume sbatch, resubmit.

**CRITICAL correctness point:** short walltimes time out **MID-SEGMENT** (a single relax segment
can exceed the walltime — e.g. 2hb: ~2.8 h/segment vs a 1 h block → NO segment ever completes). So
**segment-granularity skip is NOT enough** — resume MUST continue the interrupted segment from its
NAMD `*.restart.{coor,vel,xsc}` checkpoint, or a short-walltime job makes zero progress and loops
forever. The idempotent-skip sbatch (increment 9) handles *completed* segments; the interrupted one
needs true mid-segment restart.

**Revised Phase-5 resume TODO (increment 10 — NOT built):**
1. Remove the supervisor auto-resubmit (`poll_remote_jobs`/`reconcile_remote_job` must NOT resubmit).
2. On SLURM TIMEOUT/DEADLINE: fetch outputs (incl. restart files) back, mark the job **resumable**
   (a distinct state, not `failed` — proposal: `status=paused` or a `resumable=True` flag + a clear
   "Timed out at segment N/M — reconnect and Resume" message), keep `resubmit_count` for display.
3. `POST /md/jobs/{id}/resume-remote` (needs connection): find the interrupted segment, read its
   restart step (fetch the small `.restart.xsc`), generate a remote resume conf (port
   `_write_resume_conf`: firsttimestep + remaining steps + restart file refs, output naming so the
   next segment finds `output/<seg>.coor`), upload it + a resume sbatch (skip done → run resume conf
   → remaining segs fresh), resubmit; new SLURM id, `resubmit_count++`, back to running/queued.
4. Frontend: one-click **Resume** button on a resumable remote job (enabled only when connected).
5. Decide: same NADOC job (resubmit_count++) — proposed — vs a new child job row.

**Already shipped but now MIS-MODELED:** increment 9's `resubmit_from_scratch` + the auto-resubmit
call in `reconcile_remote_job` + `is_timeout_state` gating + `_MAX_AUTO_RESUBMITS`. Repurpose
`resubmit_from_scratch` into the user-driven resume; DELETE the supervisor auto-call. The idempotent
sbatch (skip-if-`.coor`) STAYS — it's the completed-segment half of resume.

*increment 10 (2026-07-03) — BUILT the user-driven Resume model above (auto-resubmit removed):*
- **No more auto-resubmit.** `reconcile_remote_job`: a SLURM `TIMEOUT`/`DEADLINE` now → `status=paused`
  + `resumable=True` + `failure_kind="cluster_timeout"` + a "Timed out at seg N/M — reconnect and
  Resume" message (NOT `failed`, NOT a silent resubmit). `_MAX_AUTO_RESUBMITS` and the auto-resubmit
  branch are gone; `is_timeout_state` stays (classifier). Every finished submission is recorded via
  `_append_history` into `MdJob.resume_history` (`{slurm_job_id, state, segment_reached,
  segments_total, walltime, at}`) for the expand chevron.
- **Mid-segment checkpoint resume (the crux).** `md_protocols.build_remote_resume_conf(conf_text, *,
  segment_name, restart_step, total_steps, cont_index)` — pure port of the local runner's
  `_write_resume_conf`: drops the coord/vel/box/run directives, re-emits them pointing at
  `output/<seg>.restart.{coor,vel,xsc}`, sets `firsttimestep` + runs only the remaining steps, writes
  a fresh `cont<k>.dcd`. `slurm_script.generate_sbatch(..., resume_conf_for={seg: resume_base})` runs
  the resume conf for the interrupted segment (log → `<seg>.resume.log`), skip-guards completed ones.
- **`md_executor.resume_job(job, ws, *, profile, conn)`** (user-triggered, backend present): `ls`
  scratch for finished `.coor` → find the first unfinished segment → fetch its `.restart.xsc`, read
  the step (`_read_xsc_step`) → if a usable mid-segment checkpoint, generate + upload the resume conf
  (GPUresident-stripped for CPU targets) → regenerate + upload the sbatch → `sbatch`. New SLURM id,
  `resubmit_count++`, `resumable=False`, back to `queued`. No mid-segment checkpoint (timed out before
  the first `restartfreq` write) → the segment just re-runs fresh (idempotent sbatch handles it).
- **Endpoint** `POST /md/jobs/{id}/resume-remote` (guards: alpine + `resumable` + scratch + connected;
  400/409 before any SSH — live-verified the 400).
- **Frontend:** `⟳ Resume` button (`md-jobs-resume-btn`) shown for a resumable alpine job, enabled only
  when connected (pure `mdResumeButtonState`); a collapsible **Resumptions (N)** chevron in the detail
  (`mdResumeHistoryRows`, newest-first `#n · SLURM <id> · <state> · seg x/y · walltime`); the timeout
  message shows in the detail box. `client.resumeMdJobRemote`. main.js Δ = 0.
- Tests: `test_md_executor.py` (timeout→resumable+history, resume mid-segment-from-checkpoint,
  resume-no-checkpoint-reruns-fresh; FakeConn extended with `get_contents`), `test_slurm_script.py`
  (`build_remote_resume_conf` continue/reject, resume-sbatch), `md_jobs_panel.test.js` +4
  (`mdResumeButtonState`, `mdResumeHistoryRows`). `just test` = **3794 passed**, 0 failures;
  `just test-frontend` file = 30 passed; `just smoke` = 23 passed, zero console errors.
- **NOT live-validated** (needs a real short-walltime timeout + Duo): the Resume round-trip itself —
  the `.restart.xsc` fetch + resume-conf upload + resume-sbatch submit against real scratch, and that
  NAMD actually continues the interrupted segment from the checkpoint. Everything up to the SSH is
  unit-tested (FakeConn) + the endpoint guard is live-verified. **First real test vehicle:** submit a
  small design with a deliberately SHORT walltime (amilan/`normal`), let it TIMEOUT mid-segment, then
  click Resume and confirm it continues from the checkpoint (not from segment start).
- **Open:** the resumable message renders in the red error box (mildly alarming for an expected
  timeout) — could move to a neutral/amber style. Low priority.

*increment 11 (2026-07-03) — Resume opens the REVIEW card (not pure 1-click) + LIVE-VALIDATED the
whole timeout→resume loop:*
- User refinement: Resume should let the user review/edit job details first — e.g. a short run that
  worked well → bump the walltime before officially resuming — using the SAME review popup that
  initiates a submit. So the `⟳ Resume` button now opens `md_submit_review` in **resume mode**
  instead of firing the endpoint directly.
- **`md_submit_review` resume mode** (`open(jobId, {mode:'resume'})`): fetches the recommendation
  with `current=true` (seeds the card with the job's CURRENT resources — the short walltime it just
  ran, not a fresh long auto-size), skips the already-submitted gate, titles "Resume from checkpoint
  — review" + a note, button "Resume job", posts via `api.resumeMdJobRemote`. Changing the partition
  still re-fetches a fresh consistent recommend for it (same as submit). Edits merge onto the current
  resources; no edits → keeps them.
- **Backend:** `remote-recommendation?current=true` returns `job.resources` as the baseline (when set
  + no forced partition); `POST /resume-remote` accepts a `resources` override → `resume_job(...,
  resources=...)` applies it (e.g. a longer walltime takes effect in the regenerated sbatch).
- Tests: `test_md_executor.py` +2 (`resume_job_applies_resource_override`,
  `remote_recommendation_current_seeds_from_job_resources`). `just test` = **3796 passed**,
  0 failures. Frontend vitest (review+panel+doc-header) = 56 passed; `just smoke` = 23, zero console
  errors. main.js Δ = 0.
- **LIVE VALIDATION (job `fd9e8feff41c`, 2hb, amilan, 10-min walltime):** submitted → ran →
  **TIMEOUT mid-segment-0 → `status=paused` + `resumable=True` + `failure_kind=cluster_timeout` +
  history entry + restart checkpoint fetched (step 67200/120000, aligned to restartfreq 9600), min
  skipped**. NO auto-resubmit (resub stayed 0). User clicked Resume → new SLURM `29574928`,
  `resubmit_count=1`, error cleared. So the timeout→resumable→one-click-resume loop is confirmed
  end-to-end against real Alpine.
- **CHECKPOINT-CONTINUATION PROVEN (the whole point):** the resumed run (29574928) timed out again
  mid-seg-0; its fetched `..._p10.resume.log` shows `Info: FIRST TIMESTEP 67200` + `TCL: Running for
  52800 steps` (= 120000 − 67200), the `..._p10.restart.xsc` step ADVANCED 67200 → **115200** (real
  forward progress, ~96% through seg-0), and a `..._p10.cont1.dcd` was written (partial trajectory
  preserved). So resume CONTINUES the interrupted segment from its NAMD checkpoint — it does NOT
  restart it. Each 10-min amilan block advances ~48k steps; `resume_history` now has 2 entries
  (chevron shows "Resumptions (2)"). Measured throughput ≈ 10.4 ns/day (0.096 days/ns) — what the
  learned-ns/day store will capture once a segment completes. **Phase 5 fully validated live.**


*increment 9 (2026-07-03) — CLOSES the Phase 5 box: live remote segment progress + learned ns/day + auto-resubmit:*
- **The reported symptom (the trigger for this increment):** a live CPU (amilan) run — job
  `2719c1c8700f`, SLURM 29566908 — successfully ran on Alpine and advanced p10→p50 on the
  compute node, **but the NADOC panel showed all 12 segments `pending` / segment 0.** This is
  the first *successful* multi-segment remote run (validates increments 7/8: the CPU
  GPUresident-strip + module fixes worked — the ladder actually progresses on amilan now).
- **Root cause:** `reconcile_remote_job`'s running branch only set status=`running` and returned;
  segment statuses + `current_segment_idx` were recomputed **only at terminal** (`_finalize_local_
  bookkeeping`). So a whole-ladder sbatch showed no intra-run progress.
- **Fix (live progress, `md_executor.py`):** pure `parse_progress_listing` (a remote
  `ls output/*.coor; ls *.log` dump → finished/started segment-name sets) + `apply_remote_progress`
  (marks segments done/running/pending, advances `current_segment_idx` to the running segment,
  never regresses a `done`). Async `poll_remote_progress` runs that one cheap `ls` (no file
  transfer). The reconcile running branch now calls it every supervisor tick and saves when
  progress advances. **Frontend needs NO change** — increment 4's 20 s `_remotePollTimer` already
  re-fetches `/api/md/jobs` (segments included) and re-applies the selected job's detail; it just
  had nothing new to show. Now the row/detail advance p10→p50→… live.
- **Learned ns/day (`cluster_throughput.py`, new):** small atomic JSON store in the workspace
  keyed by `(cluster, partition, size-bucket)`; pure `size_bucket` + `update_record` (running
  mean). `reconcile_remote_job` completed branch calls `_record_learned_throughput` (reads the
  freshly-fetched `metrics.jsonl` ns/day → folds into the store). `routes_md._size_prepared_job`
  now resolves the partition first, then prefers the **learned Alpine throughput** for that
  (partition, size) over the local-GPU metrics guess (which is wrong hardware for a CPU target) —
  falls back to local metrics, then the size-based guess. So the walltime estimate tightens after
  the first completed run per bucket.
- **Auto-resubmit on TIMEOUT (idempotent ladder):** `slurm_script.generate_sbatch` now guards each
  step with `if [ -f output/<conf>.coor ]; then skip; else run; fi`, so re-running the SAME sbatch
  on the SAME scratch resumes at the first unfinished segment (the interrupted one re-runs in full
  from the previous step's coords — segment-granularity resume). `md_executor.resubmit_from_scratch`
  re-issues the staged sbatch; `reconcile_remote_job` calls it on a SLURM `TIMEOUT`/`DEADLINE`
  (only — real errors FAILED/OOM/NODE_FAIL do NOT resubmit), bounded by `_MAX_AUTO_RESUBMITS=5`
  via new `MdJob.resubmit_count`. Turns a walltime under-estimate into a slowdown, not a lost run.
- Tests: `test_md_executor.py` +8 (progress parse/apply/no-regress, running-reflects-progress,
  timeout-resubmits, timeout-at-cap-fails, completed-records-throughput), `test_cluster_throughput.py`
  (7, new), `test_slurm_script.py` +1 (idempotent skip guard). `just test` = **3790 passed**,
  107 skipped, 1 xfailed, **0 failures** (baseline 3775). Backend-only, **main.js Δ = 0**.
- **NOT live-validated** (needs user + Duo): (a) the live p10→p50 refresh actually appearing in the
  panel — reconnect to Alpine so the supervisor polls job `2719c1c8700f`, then watch the segment
  progress advance; (b) auto-resubmit on a real TIMEOUT (deliberately-short walltime); (c) the
  learned ns/day tightening a second run's estimate. The pure logic + FakeConn state transitions
  are unit-tested. **Still-open modeling debt from earlier increments** (GPU `allowed_qos`/GRES for
  ami100/al40/atesting; GPU NAMD module name `namd/3.0.1_gpu`) is unchanged — correct as live sbatch
  errors surface.

*increment 12 (2026-07-03) — queued-in-cluster icon + "waiting Nm" tooltip:*
- A submitted-but-PENDING remote job used to render as a **spinner** (looked like it was running).
  Now it shows a distinct **⧗** icon with a tooltip of how long it has waited in the SLURM queue.
- Backend: `MdJob.queued_at` (epoch s) stamped when a job enters PENDING — set in
  `md_executor.submit_job` AND `resume_job` (re-stamped per resume). Serialized + load-setdefault.
- Frontend (`md_jobs_panel.js`, pure + unit-tested): `mdIsRemoteQueued(job)` (alpine + queued +
  slurm_job_id + not RUNNING — distinct from awaiting-submit), `fmtDurationShort`, `mdQueueWaitLabel`.
  Row status symbol: ⧗ (amber) + wait tooltip for a PENDING remote job instead of a spinner; detail
  status line shows `⧗ Queued Nm ago … (SLURM <id>)`. `_refreshQueuedWaits()` updates the tooltips
  in place on each 20 s poll (no list rebuild → no spinner churn; `mdListSignature` is stable while
  PENDING). Also fixed the phantom-partition class of errors this session: removed the live-invalid
  `atesting_a100` via `workspace/clusters.json` (reload-excluded → applied WITHOUT dropping the
  session); GPU short runs use **aa100 + gpu-testing** (≤1 h, live-confirmed). **TODO:** the embedded
  `alpine_profile()` in `cluster_config.py` still lists `atesting_a100` — remove it in code + update
  tests, then delete `clusters.json` so the built-in profile is the single git-synced source (a code
  edit → reloads the backend / drops the session, so do it between live sessions). Consider live
  `sinfo`/`scontrol` partition discovery to end the guess-partition/QoS/GRES churn permanently.
- Tests: `md_jobs_panel.test.js` +3 helpers, `test_md_executor.py` +2 asserts (queued_at on submit
  + resume). `just test` = **3796 passed**, frontend vitest 35, `just smoke` 23 (zero console errors).
  main.js Δ = 0. **NOT eyeballed in-browser** for the live icon (backend edit dropped the session);
  there IS a live PENDING job (`fe4cca3f3ebe`) that renders ⧗ now, but its `queued_at` is null
  (submitted pre-edit) so it shows the no-duration fallback — new submits/resumes get "waiting Nm".

*increment shipped 2026-07-03 (partition dropdown + amilan/CPU validation path):*
Precursor to the full hardening below — enables a fast-queue validation run before
investing in auto-resubmit etc. **Box stays unchecked** (learned-ns/day, auto-resubmit,
session-expiry UX still TODO).
- **`recommend(partition=...)`** — optional forced partition (`cluster_resources.py`).
  When set, kind/gpus/cores/gres_type/qos/throughput-class/cost are ALL re-derived from
  that partition so we never ship a self-inconsistent set (e.g. a CPU partition with a
  gpu-* QoS + a100 GRES). Unknown name → `ValueError`. Auto-pick path unchanged when
  `partition=None`.
- **Endpoint** `GET …/remote-recommendation?partition=<name>` — passes it through
  (`_size_prepared_job` gained a `partition` arg); `ValueError`→400. Response now also
  carries **`available_partitions`** (`[{name,kind,gpu_model}]`) to populate the dropdown.
- **Review card** (`md_submit_review.js`) — the Edit-resources drawer's Partition field
  is now a **`<select>`** built from `available_partitions` (pure `partitionSelectOptions`,
  unit-tested). Changing it **re-fetches** the recommendation forcing that partition and
  re-renders the whole card (factory now holds `_ctx={jobId,clusterName,editOpen}` across
  re-fetch; `_load(partition)` is the shared fetch+render). This keeps the shown resources
  consistent instead of naively overriding just the partition string. Client
  `getMdRemoteRecommendation(id,{partition})` adds the query param.
- **amilan/CPU path verified** — forcing amilan yields cpu/gpus=0/plain `long` QoS/no
  GRES; `generate_sbatch` then emits the CPU branch (`mpirun -np $SLURM_NTASKS namd3`,
  `--constraint=ib`, `namd/3.0.1_cpu` module, no `--gres`, no GPU warning). Eyeballed live
  against real job `03302b74a7fa`. **Live-validation risk:** whether `namd/3.0.1_cpu` is an
  MPI build that `mpirun` can launch is untested on Alpine (matches the Appendix recipe).
- Tests: `test_cluster_resources.py` +3 (forced cpu/gpu/unknown), `test_md_executor.py` +2
  (endpoint lists partitions + honours forced + 400), `md_submit_review.test.js` +3
  (`partitionSelectOptions`). `just test` = 3732 passed (1 flake `test_md_list_includes_size`
  — passes in isolation, xdist active-design isolation). Frontend touched vitest green (44).
  **main.js Δ = 0.** DOM click-through of the `<select>` NOT exercised in-browser (needs the
  card open on a prepared alpine job); data contract it consumes verified live via curl.

*increment 2 shipped 2026-07-03 (QoS dropdown + FIRST live monitoring validation + sbatch `set -u` fix):*
- **QoS dropdown** — mirror of the partition one. `ClusterProfile.qos_tiers_for_kind(kind)`
  returns the tiers valid for a partition kind (gpu→`gpu-*` only, cpu→plain only); endpoint
  adds **`available_qos`** `[{name,max_walltime_h}]` (keyed off the resolved recommendation
  kind, so it updates when the partition dropdown re-fetches). Card's QoS field is now a
  `<select>` (pure `qosSelectOptions`, labels show `≤N h` ceilings). QoS is a plain override
  (no re-fetch — it doesn't change cores/gpus/gres).
- **CRITICAL sbatch fix (`slurm_script.py`)** — the first real Alpine run (job `3ac8c166ed2e`,
  amilan, 1 h walltime, SLURM 29560924) **FAILED instantly** with `.err` = `/etc/profile:
  line 47: HISTCONTROL: unbound variable`. Cause: the script ran `set -euo pipefail` BEFORE
  `source /etc/profile`, and Alpine's profile references unbound vars → `set -u` aborted the
  job before NAMD started. Fix: source `/etc/profile` FIRST, then `set -eo pipefail` (dropped
  `-u` — HPC profile/module scripts routinely reference unbound vars). Regression test added.
  **This was blocking every remote run** (GPU too — same header).
- **Live monitoring validation (the win):** the failed run *proved the monitor pipeline works
  end-to-end* — the supervisor polled `squeue`→`sacct`, mapped the real state to `FAILED`, set
  `job.error="Remote job 29560924 ended in SLURM state FAILED."`, and `fetch_outputs` pulled
  the SLURM `_29560924.out/.err` back locally (that's how we read the cause). So poll→status→
  fetch is confirmed against a real job. **NOT yet validated: the running→completed happy path**
  (the job never ran NAMD). Needs a fresh resubmit now the `set -u` bug is fixed — a small
  amilan + `testing` QoS + short walltime job is the right validation vehicle.
- Tests: `test_cluster_config.py` +1 (`qos_tiers_for_kind`), `test_slurm_script.py` +1
  (source-before-errexit regression), `test_md_executor.py` endpoint test +available_qos asserts,
  `md_submit_review.test.js` +2 (`qosSelectOptions`). Live: endpoint returns correct CPU/GPU
  `available_qos`; fixed sbatch header eyeballed. **main.js Δ = 0.** `<select>` DOM click-through
  still not browser-exercised (same caveat).

*increment 3 (same session) — QoS is PER-PARTITION, not per-kind (2nd live rejection) + running-state monitoring:*
- After the `set -u` fix, the resubmit (amilan + `testing` QoS) hit a **new live sbatch
  rejection**: *"The amilan partition accepts the following QoS values: admin or normal or
  long"*. So `testing`/`mem`/`compile` are NOT valid on amilan (they belong to atesting/amem/
  acompile). My kind-based `available_qos` was wrong — it would offer testing-on-amilan, the
  exact invalid combo the dropdown exists to prevent.
- Fix: `Partition.allowed_qos: list[str]` allow-list per partition (amilan=[normal,long] LIVE-
  confirmed; aa100=[gpu-normal,gpu-long,gpu-testing] live-confirmed; others best-guess by
  family). New `ClusterProfile.qos_tiers_for_partition(name)` (prefers the allow-list, falls
  back to kind split). Endpoint's `available_qos` now keys off the **recommended partition**,
  not its kind. `qos_tiers_for_kind` kept as the fallback. Tests updated: amilan → only
  {normal,long}. (Bonus live intel: CURC renames `amilan`→`acpu` on 2026-08-05 — future churn.)
- **Resubmitted amilan/normal/50min → SLURM 29561635, accepted.** Supervisor live-tracked it
  through `PENDING` (verified continuously for 8+ min — queue slow today). **Monitoring now
  validated for: queued/PENDING (live), failed+fetch (prior run).** `RUNNING→completed` still
  pending the real Alpine queue (scheduler-bound, not a code gap) — job 3ac8c166ed2e will
  advance under the supervisor whenever it dispatches; check the panel / `GET /api/md/jobs`.
- **Open modeling debt:** GPU/atesting `allowed_qos` + GRES types for ami100/al40/atesting_a100
  are still best-guess; correct them as live sbatch errors surface (same as the amilan lesson).

*increment 4 (same session) — FRONTEND live-refresh for remote jobs (the panel was frozen):*
- Symptom: after an out-of-band resubmit the panel showed a stale "Running on Alpine" + the
  OLD run's error ("Remote job 29560924 ended in FAILED") while the backend was clean
  (29561635/PENDING/error null). Root cause: **remote jobs get NO live update in the UI.**
  `_fetchJobs()` had **no periodic timer** (only panel-open + user-action triggers), and the
  per-job WebSocket only pushes for LOCAL running jobs. The backend supervisor polls SLURM and
  updates job.json, but nothing told the panel. Compounding it: `_selectJob` early-returns for
  an unchanged selection, so even a manual `_fetchJobs` refreshed the list rows but NOT the
  selected job's DETAIL (status/error) — remote detail never updated without reselecting.
- Fix (all in `md_jobs_panel.js`, panel-cohesive): a gated `_remotePollTimer` (20 s) started in
  `_onOpen`, stopped on collapse. `_maybePollRemote()` polls only when `hasActiveRemoteJob(_jobs)`
  (new exported pure helper: an Alpine job that is submitted-and-active — `mdJobIsActive` &&
  `execution_target==='alpine'`), then re-applies the selected remote job's detail explicitly
  (`_applyJobState`) to clear a resolved error / refresh SLURM state. `mdListSignature` already
  guards the list rebuild, so idle ticks don't churn the DOM.
- Also noted (not yet changed): the list-row remote badge tooltip hardcodes "Running on Alpine
  (SLURM …)" for ANY submitted job regardless of PENDING/FAILED/COMPLETED — mildly misleading
  wording, low priority.
- Tests: `md_jobs_panel.test.js` +2 (`hasActiveRemoteJob`). `just test-frontend` touched-files
  green (48); **`just smoke` = 23 passed, zero console errors** (stateful-change gate). main.js
  Δ = 0. Verified in-app pending: the user should reopen the MD panel to pick up the HMR change —
  the stale error clears, id shows 29561635, and the row/detail then auto-advance every 20 s.

*increment 5 (2026-07-03) — session-expiry UX + SSH error classification (the "why did it drop?" piece):*
- **`classify_ssh_error(text) -> kind`** (`cluster_ssh.py`, pure/unit-tested) buckets an
  opaque asyncssh/transport message into `timeout | auth | network | permission |
  filesystem | unknown` (ordered keyword match, specific-first). `ClusterSSHError` now
  carries `.kind` (auto-derived from its message unless one is passed).
- **`ClusterConnection` records the last classified error.** New `_fail_transport(msg)`
  (replaces the bare `_mark_expired`) records `last_error`/`last_error_kind` AND flips the
  session to EXPIRED in one place; all transport ops (`run`/`sftp_put`/`sftp_get`) and the
  connect-failure path route through error recording. `status()` now also returns
  `last_error` + `error_kind` (cleared on successful connect + on disconnect). So a
  supervisor SSH op that hits a broken pipe / timeout leaves an actionable reason in the
  status snapshot, not just a state flip.
- **Frontend surfaces it without a user action.** `cluster_connection.js` gained a 15 s
  status poll (only fires while `connected`, cleared on dispose) so a backend-detected
  expiry flips the chip to "Reconnect" on its own. New pure `expiryMessage(status)` maps
  kind→human prefix + raw error ("Connection lost — Broken pipe"); shown in the chip
  tooltip for expired/failed-connect states.
- **Offline viewability** was already satisfied — `poll_remote_jobs` no-ops when
  disconnected and jobs read from local `job.json` — so no change needed there.
- Tests: `test_cluster_ssh.py` +9 (classify table, `.kind` derivation, transport/timeout/
  connect-failure record classified status, reconnect clears stale error; updated the
  status-dict equality assert for the 2 new keys). `cluster_connection.test.js` +5
  (`expiryMessage`). `just test` = **3753 passed**, 107 skipped, 1 xfailed, **0 failures**
  (the old hardcoded `/home/joshua/…2x2_OH_test.nadoc` fixture no longer fails on this
  machine). Frontend vitest for the file = 15 passed. **`just smoke` = 23 passed, zero
  console errors.** main.js Δ = 0.
- **Still TODO for the Phase 5 box:** learned ns/day (needs a completed remote run to learn
  from — none yet), auto-resubmit-from-checkpoint on TIMEOUT (needs a timeout run to
  validate). **NOT VERIFIED IN APP** for the *live* expiry→Reconnect transition — that
  needs a real session to actually drop (Duo); the pure logic + chip poll are unit-tested,
  and the chip renders clean under `just smoke`.

*increment 8 (2026-07-03) — make GPU (aa100) submissions load a GPU NAMD build:*
- The mirror of increment 7: a *GPU* Alpine run would FATAL identically, because the profile
  loaded only `namd/3.0.1_cpu` (a CPU/multicore build) for ALL partitions — so aa100's `+devices`
  exec ran against a build with no GPU-resident support. Confs KEEP `GPUresident on` for GPU (not
  stripped), so the module MUST be a CUDA build.
- **Kind-aware module loads.** `ClusterProfile` gained `gpu_module_loads` + `modules_for(gpu)`:
  GPU targets load the CUDA/GPU-resident NAMD build, CPU targets the MPI build. Alpine profile now
  ships `gpu_module_loads=["gcc/14.2.0", "namd/3.0.1_gpu"]` (CPU set unchanged: gcc+openmpi+namd_cpu).
  `slurm_script._module_block(profile, gpu)` uses it; the CPU-module WARNING now checks the
  *resolved GPU* module set (fires only if a GPU partition still resolves a `namd/*_cpu` build).
  Both roundtrip through `clusters.json` (`gpu_module_loads` key).
- **The GPU module name is a best-guess** (`namd/3.0.1_gpu`, from CURC's `_cpu`→`_gpu` convention —
  web-searched, not doc-confirmed; the exact string needs live `module avail namd`). So:
  **live discovery** — `md_executor.list_namd_modules(conn)` + pure `parse_namd_modules` run
  `module -t avail namd` on the cluster; new route `GET /api/cluster/namd-modules` (409 if not
  connected) returns the real list. If the guess is wrong, the `module load` fails and increment-6
  error surfacing shows it on the frontend; fix via the Edit drawer partition or `clusters.json`.
- Eyeballed real manifest: **GPU (aa100)** header → `module load gcc/14.2.0 namd/3.0.1_gpu`,
  `namd3 +p8 +setcpuaffinity +devices 0 …`, `--gres=gpu:a100-40gb:1`, `--qos=gpu-long`, NO warning,
  confs keep GPUresident. **CPU (amilan)** → `namd/3.0.1_cpu`+openmpi, `mpirun`, `--constraint=ib`,
  confs GPUresident-stripped. Tests: `test_cluster_config.py` +3 (`modules_for` gpu/cpu/fallback +
  json roundtrip), `test_slurm_script.py` +1 (cpu module block) + reworked 3 (module-block/warn),
  `test_md_executor.py` +3 (`parse_namd_modules`, `list_namd_modules`). `just test` = **3775 passed**
  (1 known xdist flake `test_md_list_includes_size`, passes in isolation, untouched file). Backend-
  only, main.js Δ = 0. **NOT live-validated**: needs `GET /api/cluster/namd-modules` (Duo) to confirm
  `namd/3.0.1_gpu` exists, then a real aa100 submit. Possible follow-up: surface the discovered
  modules as a picker in the review-card Edit drawer.

*increment 7 (2026-07-03) — strip `GPUresident` from confs for CPU targets (the p50 FATAL root cause):*
- Root cause of increment 6's `FATAL ERROR: GPUresident not supported on regular multicore
  builds`: NADOC's prep bakes `GPUresident on` into every **fast (HMR + 4 fs) segment conf**
  (`_p50`/`_p100`) because the local pipeline is GPU-resident (`md_protocols._common_header`,
  `gpu_resident=fast`). The `_p10` warmup phase (rigidBonds none, 1 fs, no HMR) never gets it.
  The remote chain runs `min → 01_p10 → 01_p50 → …`, so on an **amilan (CPU/multicore)** target
  the min + `01_p10` ran fine and `01_p50` FATALed. **Submission only adapted the sbatch exec
  line (GPU `+devices` vs CPU `mpirun`) — the staged `.conf` files were uploaded verbatim**, so a
  CPU run inherited a GPU-only directive. (Note: cores need NO conf amendment — they're a
  command-line flag `+p<cores>` / `mpirun -np $SLURM_NTASKS`, not a conf setting. `GPUresident`
  is the *only* GPU-build-specific conf directive; the diff of p10↔p50 is psf/hmr, rigidBonds,
  timestep, GPUresident, output names, run steps — all CPU-valid except GPUresident.)
- Fix: `md_protocols.strip_gpu_resident(conf_text)` (pure, idempotent, no-op when absent) removes
  the whole `GPUresident …` line. `slurm_script.is_gpu_target(profile, resources)` is now the
  **single source of truth** for the GPU/CPU branch (used by `generate_sbatch` AND staging).
  `md_executor.submit_job` amends **every** staged `.conf` through `strip_gpu_resident` when
  `not is_gpu_target` (uploads amended text instead of the raw file), so all confs are consistent
  with the chosen partition. GPU targets keep the directive (matches the `+devices` exec line).
- Verified against the REAL failed conf (`…_01_300K_NPT_ENM_k0p5_p50.conf`): strips exactly 1 line,
  everything else intact. Tests: `test_slurm_script.py` +6 (`is_gpu_target` gpu/cpu/unknown,
  `strip_gpu_resident` remove/noop/idempotent), `test_md_executor.py` +2 (submit amends for CPU,
  keeps verbatim for GPU — FakeConn now captures uploaded text). `just test` = **3769 passed**,
  0 failures. Backend-only, main.js Δ = 0. **NOT live-validated** — needs a fresh amilan resubmit
  (Duo) to confirm the whole ladder now runs on CPU. Still open: the GPU NAMD module name for
  aa100 (so a *GPU* Alpine run works — currently the profile ships `namd/3.0.1_cpu`, which would
  FATAL the same way on aa100 since the exec still uses `+devices`).

*increment 6 (2026-07-03) — surface the ACTUAL NAMD/SLURM error on the frontend (not just "FAILED"):*
- Symptom: a remote run got through minimize + into segment p50, then the p50 log FATALed
  with `FATAL ERROR: GPUresident not supported on regular multicore builds` (the GPU exec
  line `namd3 +devices …` ran against a *regular multicore* NAMD build — the GPU module name
  is still a TODO). NADOC only showed the bare `Remote job <id> ended in SLURM state FAILED.`
  — the real cause sat unread in the fetched log.
- **`extract_error_line(text)`** (`md_vram.py`, pure/unit-tested) pulls the single most-
  informative error line from a NAMD/SLURM log, most-specific-first: NAMD `FATAL ERROR:` →
  SLURM `DUE TO TIME LIMIT`/OOM → `slurmstepd`/`srun: error:` → `set -u` unbound-variable →
  generic `ERROR:`/abort. Capped ~300 chars. `+ extract_error_line_from_file` (tail only).
  Complements the existing `classify_failure_log` (which gives the *kind* for the Fix remedy).
- **Remote path** (`md_executor.reconcile_remote_job` failed branch): new `_scan_logs_for_error`
  scans the already-fetched logs — NAMD `*.log` newest-first (failing segment is freshest),
  then SLURM `*.err`/`*.out` — and appends the excerpt to `job.error` + sets `failure_kind`.
  So `job.error` becomes e.g. *"Remote job 29561635 ended in SLURM state FAILED. FATAL ERROR:
  GPUresident not supported on regular multicore builds (see …_p50.log)"*. No frontend change:
  the detail error box already renders `job.error` with `white-space:pre-wrap;word-break:break-word`.
- **Local path** (`namd_runner.py`): the min + segment failure messages now also inline the
  extracted FATAL line (was just "See <log>"), so local NAMD failures read the same way.
- Verified `_scan_logs_for_error` against the REAL fetched log (job `3ac8c166ed2e`) → extracts
  the GPUresident FATAL exactly. Tests: `test_md_vram.py` +5 (`extract_error_line` NAMD/SLURM/
  none/file), `test_md_executor.py` +3 (failed-reconcile surfaces cause, scan priority NAMD>err,
  clean→None). `just test` = **3761 passed**, 107 skipped, 1 xfailed, 0 failures. Backend-only,
  main.js Δ = 0. **Note:** the already-terminal job `3ac8c166ed2e` keeps its old bare error (the
  supervisor only reconciles *active* jobs) — the richer message shows on the next failure.

**Changes:**
- **Learned ns/day.** Cache measured cluster ns/day per (system-size bucket,
  partition) from completed remote jobs (small JSON in workspace); Phase-2
  `recommend()` uses it instead of the local-GPU guess. First run per bucket is a
  guess by design; tightens after.
- **Auto-resubmit-from-checkpoint chain.** On SLURM `TIMEOUT`, relaunch from the
  last restart files (NADOC already writes them + supports resume — [[md-job-system]]).
  Turns walltime under-estimation into a slowdown, not a failure.
- **Session-expiry UX.** Detect connection errors (timeout/broken-pipe/"not
  connected") across cluster ops → chip → Expired → "Reconnect"; jobs remain
  viewable offline from local `job.json`. Classify SSH errors
  (network/auth/permission/filesystem/timeout) for actionable messages.

**Done criteria:**
- `just test` + `just test-frontend` green with new unit tests (ns/day bucketing,
  resubmit trigger on TIMEOUT, error classification).
- Expiry→reconnect exercised in app; auto-resubmit validated on a deliberately
  short walltime (needs user + Duo).

*shipped:* _(fill in)_

---

## Appendix — portable reference data (from NAMDRunner; clone not needed)

**Auth reality (CURC Alpine):** SSH **keys are disabled**; password + **Duo 2FA**
only, via keyboard-interactive. "Connect" is inherently ≥2-touch (password + phone
push/passcode) — cannot be fully headless. Hold creds in memory, clear on
disconnect, never log/persist. Reuse one connection (SSH setup ~500 ms); cap
concurrent connections ~3.

**Host:** `login.rc.colorado.edu`.

**Two-filesystem model:**
- `/projects/$USER/nadoc_jobs/{job_id}` — persistent, small. Upload + keep results here.
- `/scratch/alpine/$USER/nadoc_jobs/{job_id}` — fast, **auto-purged**. Jobs MUST run here.
- Flow: upload→`rsync` project→scratch on submit; run; `rsync` scratch→project on completion.

**sbatch recipe (CPU build shown; use a GPU NAMD module + GPU exec line by default):**
```
#!/bin/bash
#SBATCH --job-name=<name>
#SBATCH --output=<name>_%j.out
#SBATCH --error=<name>_%j.err
#SBATCH --partition=<amilan|aa100|...>
#SBATCH --nodes=1
#SBATCH --ntasks=<cores>
#SBATCH --time=HH:MM:SS
#SBATCH --mem=<N>GB
#SBATCH --qos=<normal|long|mem|testing>
#SBATCH --constraint=ib          # InfiniBand
source /etc/profile
export SLURM_EXPORT_ENV=ALL       # required for OpenMPI
module purge
module load gcc/14.2.0 openmpi/5.0.6 namd/3.0.1_cpu   # swap for GPU module
cd <scratch_dir>
mpirun -np $SLURM_NTASKS namd3 config.namd > namd_output.log   # CPU
# GPU-resident alternative: namd3 +p<cores> +devices 0 config.namd > namd_output.log
```
Submit: `cd '<scratch_dir>' && sbatch job.sbatch`; parse `Submitted batch job <digits>`.

**Status polling:** active → `squeue -j <ids> --format='%i|%T' --noheader`; jobs
missing from squeue → `sacct -j <ids> --format=JobID,State --parsable2 --noheader`.
Batch comma-separated ids; cache 30–60 s. Status-code map:
- `PD/PENDING`→pending; `R/RUNNING`, `CG/COMPLETING`→running; `CD/COMPLETED`→completed;
- `CA/CANCELLED`→cancelled; `F/FAILED`, `TO/TIMEOUT`, `NF/NODE_FAIL`, `PR/PREEMPTED`,
  `OOM/OUT_OF_MEMORY`, `BF/BOOT_FAIL`, `DL/DEADLINE`→failed.

**SFTP:** chunked upload 256 KB, per-chunk timeout ~300 s, flush per chunk (avoids
timeout accumulation on multi-MB PSF/DCD). Recursive mkdir for job dirs.

**Alpine capabilities (partitions):** `amilan` (default CPU, ≤64 cores, 3.75 GB/core),
`amilan128c` (≤128, 2.01), `amem` (high-mem, ≤128, 21.5), `aa100` (**NVIDIA A100**, 3
GPU), `ami100` (AMD MI100), `al40` (NVIDIA L40), `atesting`/`atesting_a100`/
`atesting_mi100` (quick testing), `acompile`.
**QoS:** CPU partitions (amilan/amem/…) use `normal` (≤24 h, default), `long`
(≤168 h), `mem` (≤168 h, amem, ≥256 GB), `testing` (≤1 h), `compile` (≤12 h).
**GPU partitions (aa100/al40/ami100/…) namespace their QoS as `gpu-normal` /
`gpu-long` / `gpu-testing`** — SLURM **rejects** the plain names on aa100 (live-
confirmed 2026-07-03: *"The aa100 partition accepts the following QoS values: admin
or gpu-normal or gpu-long or gpu-testing"*). `recommend()` picks the name by
partition kind via `ClusterProfile.qos_for(kind, tier)`. GPU ceilings assumed to
mirror CPU (24/168 h) — **if SLURM later rejects the walltime, the real gpu-long cap
is lower; set it in `workspace/clusters.json` or lower walltime in the review card.**
**Billing (SU):** CPU 1.0 SU/core-hour; GPU 108.2 SU/gpu-hour.
`cost = cores×hours×1.0 + gpus×hours×108.2`.

**NAMDRunner module layout** (for design reference only, if re-reading the clone):
`src-tauri/src/` — `ssh/` (manager, sftp, commands, paths), `slurm/` (commands,
script_generator, status), `automations/` (job_creation/submission/sync/completion/
deletion), `cluster.rs` + `cluster/alpine.json` (capabilities), `security/` (shell
escaping, input sanitization). Docs: `docs/{SSH,AUTOMATIONS,ARCHITECTURE}.md`.
