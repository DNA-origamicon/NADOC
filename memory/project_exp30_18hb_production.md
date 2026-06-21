---
name: project_exp30_18hb_production
description: 18hb full-origami production MD run (unattended) — topology scale-bug fixes + self-healing monitoring stack
metadata:
  type: project
---

**COMPLETED 2026-06-20 — FULL SUCCESS: 12/12 health gates passed, C1' held 99–100%
through true k=0 (no melt), WC 95→78. ~6.1 days, 0 crashes. Final report:
experiments/exp30_18hb_production/REPORT.md.** Confirms exp29's prediction that a large
salted bundle survives true k=0 where 2hb/6hb melted.

Unattended production MD run of `workspace/18hb.nadoc` (224-strand 18-helix bundle,
no extra bases) launched 2026-06-14. Job id in `experiments/exp30_18hb_production/JOB_ID`
(e29d1e5d5ace). Protocol `equilibrium_aware_namd` = mgh_slow_release ENM ladder
(k=0.5→0.1→0.01→k=0) + full psfgen topology. Solvated **~2.98M atoms**; ladder ~19.2 ns
→ expect several days on the RTX 3080 Ti. Buffer 50 mM NaCl + 12.5 mM Mg (exp29 win);
min 24k steps.

**Two scale-only topology bugs fixed to get here** (only bite >99999 atoms / >62 strands,
so 2hb/6hb always worked, 18hb never did):
1. `namd_topology.py` `_psfgen_pdb_record`/TER used `{serial:5d}` → overflowed the 5-col
   PDB serial field past 99999, shifting every downstream column → psfgen read a corrupt
   resid → fatal `patch DEO5 DNAA:1 no residue 1`. Fix: `_h36(serial, 5)` (hybrid-36).
2. `_psf_segid(chain_id)[:4]` collapsed 224 strands into 8 colliding segids (DNAA ×27).
   Fix: drop `[:4]` — full ≤8-char segids; psfgen + MDAnalysis accept them (verified). This
   also makes the health pairing (keys cross-strand C1' pairs on full segid) correct.
3. Related correctness fix: `md_protocols.py` `_parse_base_ring_residues` grouped residues
   in a **global dict keyed on lossy (chain,resid,resn)**. `_chain_char` cycles every 62
   strands and resids repeat across strands, so ~half of 18hb's 14172 residues collided and
   **merged into one ENM node** (nonsense COM). Fixed to **contiguity grouping** (new node on
   identity change vs previous atom + TER reset). Verified: ENM now has 14172 nodes (was
   ~9760 merged). Regression tests in test_namd_topology.py + test_md_declash.py.

**Throughput (2026-06-14):** GPU-resident (`CUDASOAintegrate on`, deprecated alias
for `GPUresident`) benchmarked **2.97 ns/day vs 1.38 baseline = 2.2×** (physics
identical). Not 10× — elongated-box PME (Z≈1382 Å) is the ceiling. Enabled in the 12
dynamics-segment package confs only (not the generator). ETA ~6–7 days.

**Resume bug fixed (`namd_runner._write_resume_conf`):** emitted `run upto <total>`
→ NAMD 3.0.2 Tcl `run` rejects `upto` (`first arg not norepeat`), so EVERY checkpoint
resume would have died (latent — never exercised until the GPU benchmark forced the
first resume). Now `run <remaining>` + `firsttimestep`. Test `test_md_resume.py
::test_rewrites_directives` had encoded the buggy `run upto` expectation — corrected.

**Monitoring stack (3 layers):**
- OS watchdog `scripts/watchdog_18hb.sh` (nohup, 600s) — relaunches `run_18hb.py --resume`
  iff the run process died and the job is resumable. **Session-independent** (survives Claude
  exit). The durable layer.
- Agent crons (this session, **session-only**, 7-day expiry): active every 2h (`3fe869d7`) +
  twice-daily backstop 08:47/20:47 (`ed2aaaf1`). Re-invoke the agent to interpret
  `scripts/monitor_18hb.py` and act. **Die if the Claude session closes** → only the watchdog
  + nohup'd run survive then.
- `scripts/monitor_18hb.py` is **strictly read-only**. Do NOT add `reconcile_job_status` to
  any poller: it mutates+saves and falsely marks a live run `failed` during the minimisation
  phase (cost me one false-fail; repaired). Only `run_job` / `--resume` may reconcile.

Procedure + failure playbook (health-gate fail, k=0 melt fallback = hand off at last passing
k, NAMD crash, OOM): `experiments/exp30_18hb_production/README.md`. Live log: `MONITOR_LOG.md`;
final `REPORT.md` on terminal state. See [[project_md_prep_relaxation]] (exp29) for the
buffer/min rationale and the k=0-melt history.

**Caveat:** `backend/core/atomistic.py` has uncommitted WIP that fails 3 round-trip RMSD tests
(stale committed reference PDB vs shifted P placement) — pre-existing, not from this work; the
18hb build audit passed, but if a starting-geometry NAMD blow-up appears, suspect it.
