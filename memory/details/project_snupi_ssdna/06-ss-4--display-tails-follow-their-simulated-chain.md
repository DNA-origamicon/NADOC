# SS-4 — display: tails follow their simulated chain — supporting detail

[Topic head](../../project_snupi_ssdna.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## SS-4 — display: tails follow their simulated chain

**Built — see the ✅ SS-4 section at the top.** The plan below is kept for its reasoning. Two things it
did not anticipate: (a) **47% of every frame was beads the renderer cannot draw** (bare-lattice bp with
no strand — fixed, and it improved the Kabsch fit); (b) the mean-shape payload must carry an actual tail
CONFORMATION, not the time-mean of the tail beads (the mean of a coil is not a coil). The 11 fully-unmeshed
helices it asks about: their beads are exactly the tails, and they are now emitted from the tail block
rather than through the per-helix loop, which never visits an unmeshed helix.

**Goal.** The figure payoff. Overhangs wave.

**Build.** `deformed_positions_with_axis` currently **omits** every overhang bead and every fully-unmeshed
helix, deliberately, so the render keeps them at their rendered pose (the VoltronCore DISPLAY fix in
[[project_snupi_gaps]] — read that section before touching this function; it is subtle and it was hard-won).
Now those beads have simulated positions: map each overhang/scaffold-end render bead onto its ss-node
chain and emit it. **The Kabsch fit must still be computed on the duplex core only** — that was the
original bug (floppy misplaced beads skewed the global fit and produced a phantom 7.6 nm duplex offset).

Use `frames_all` (core+tails) and `tail_nodes` — each carries its render-bead key `(helix_id, bp,
direction)` plus `overhang_ids`. NB the tail bead's *simulated* position bears no relation to the
rendered pose: a tail is a compact thermal coil ~2–5 nm across, not the extended chain at the 0.34 nm
duplex rise the renderer draws. That is the point, and the display must not try to reconcile them.
`tails=`/`tail_max_nt=` are not plumbed through the API/job layer yet (SS-2/SS-3 reach them only from
`simulate_equilibrium`) — SS-4 has to add that.

Also revisit the 11 fully-unmeshed helices: with tails meshed, several of them may now have nodes.

**Gate.** Load VoltronCore in the running app, run a dynamics+hydro job, play the trajectory. The duplex
core must look exactly as it does today (regression) and the tails must visibly fluctuate. Zero console
errors (`just smoke`). This phase is **not done without the live-app exercise** — per CLAUDE.md, and
because "looks right" is the actual deliverable here.

---

## SS-5 — VoltronCore validation + figures

- Static shape with SS-1 bridging elements vs the mrDNA/oxDNA baseline (~1.7 nm from design). The
  diagonal-material shape fix ([[project_snupi_gaps]], 2026-07-13) put SNUPI at 3.3 nm; does correct
  bridging ssDNA move it?
- Dynamics + coarse hydro trajectory: breathing mode + frequency (`breathing_mode_pca`), τ_stokes vs
  τ_rpy speedup, DCCM.
- Tail statistics from the trajectory: per-overhang `⟨R_ee⟩` vs the WLC prediction; do the 28-mers
  sample more configuration space than the 3-mers, as they must?
- The figure: VoltronCore trajectory animation with fluctuating overhangs.
- Reconcile [[project_snupi_gaps]] (mark **G9 closed**; its "Phase E — situational" framing is now wrong)
  and [[project_snupi_dynamics]] (tails are a new force/mass/drag term in the Langevin loop).
- **New in SS-5 (from SS-4's measurements):** the duplex core's displayed jitter is ~2.5× its physical
  node motion — the winding rebuilds the cross-section frame from thermally-noisy nodes 0.34 nm apart.
  Wind on a smoothed/reference axis + add the node displacement as a translation. Pre-existing, affects
  every SNUPI/CanDo trajectory, and it is what currently flattens the visual contrast between a boiling
  core and the waving tails.

---

## Kickoff prompt for a fresh session (edit the phase name)

> **Continue the SNUPI ssDNA plan — Phase SS-N.** Read `memory/project_snupi_ssdna.md` first: the HANDOFF
> block at the top gives phase status, and the "Architectural decisions" section is binding (in particular:
> **free ssDNA tails enter the DYNAMICS engine only — never the static K or the NMA**, because floppy-tail
> eigenvalues would flood the 200-mode basis and destroy the validated duplex-core RMSF). Skim
> `memory/project_snupi_gaps.md` (static mimic, gap G9, and the VoltronCore DISPLAY fixes — read those
> before touching `deformed_positions_with_axis`) and `memory/project_snupi_dynamics.md` (the Langevin/RPY
> engine and the coarse-blob hydrodynamics you will be extending).
>
> The target design is `workspace/VoltronCore.nadoc` (59 helices, 7088 bp nodes, 866 nt of ssDNA — 55
> overhang TAILS (571 nt) + 35 cross-helix scaffold HOPS (295 nt); no dangling ends, no interior gaps).
> The goal is both scientific fidelity *and* trajectories that look genuinely MD-simulated, which is
> SNUPI's whole selling point.
>
> Build only Phase SS-N's scope, hit its stated oracle/gate, then update this file's HANDOFF table + add
> the phase's results sub-section. Guardrails: everything gated behind `material="snupi"` (cando stays
> byte-identical); Three-Layer Law (ssDNA positions are Physical/display-only, never written back to
> topology); `_PHASE_*` constants locked; **any question about strand polarity, tail anchoring, or domain
> traversal → ASK the user, implement nothing**; a mechanical unit test per new piece; `just test-smart`
> (and `just test-frontend` if you touch JS) before claiming done; `main.js` LOC Δ = 0. Commit only when asked.

## References
- Literature: SNUPI ssDNA element — *ACS Nano* 2021 15(12):20430 ([doi:10.1021/acsnano.1c08861](https://pubs.acs.org/doi/10.1021/acsnano.1c08861));
  SNUPI base — *ACS Nano* 2021 15(1):1002; SNUPI dynamics — *Nat Commun* 2023 14:7079; CanDo ssDNA (mFJC) —
  *NAR* 2012 40(7):2862 ([PMC3326316](https://pmc.ncbi.nlm.nih.gov/articles/PMC3326316/)); engineered ssDNA
  gaps soften origami up to 70% — *ACS Nano* 2019 ([doi:10.1021/acsnano.9b03770](https://pubs.acs.org/doi/10.1021/acsnano.9b03770)).
- Ground truth on this machine: `~/SNUPI/Default.snp` (lines 88–153 = the ssDNA parameter block).
- Code: `fem_solver.py` (`build_fem_mesh`, `_add_ssdna_hops`, `assemble_global_stiffness`,
  `deformed_positions_with_axis`), `snupi_material.py`, `snupi_dynamics.py` (`simulate_equilibrium`),
  `snupi_hydro_coarse.py` (`blob_partition`, `build_coarse_friction`), `snupi_hydrodynamics.py`.
- Related: [[project_snupi_gaps]] (G9), [[project_snupi_dynamics]], [[snupi-mimic]], [[project_cando_fem]],
  [[feedback_staples_are_user_intent]] (unstapled scaffold is deliberate ssDNA — the reason this matters).
