---
name: atomistic_propagator
description: Loop head + handoff for the learned atomistic-propagator MVP (NAMD-surrogate + uncertainty). Resume from HANDOFF.
metadata:
  type: project
---

# Atomistic Propagator MVP — Loop Head & Handoff — topic guide

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

BLADE/propagator work is shelved (July 20; see [BLADE status](project_blade_frontend.md)). The old build and data-scaling handoffs below are historical, not an active task queue. [OpenMM implicit](project_openmm_implicit.md) records the successor. Preserve optional ML imports and frozen reference data; resuming experiments requires a specific request.

- [Overview — continued detail](details/project_atomistic_propagator/01-overview_archive.md)

<a id="atomistic-propagator-mvp--loop-head--handoff"></a>
- [Atomistic Propagator MVP — Loop Head & Handoff](details/project_atomistic_propagator/01-overview_archive.md#atomistic-propagator-mvp--loop-head--handoff)

<a id="overarching-goal-user-spec-2026-07-18--the-north-star"></a>
- [OVERARCHING GOAL (user spec, 2026-07-18) — the north star](details/project_atomistic_propagator/01-overview_archive.md#overarching-goal-user-spec-2026-07-18--the-north-star)

<a id="what-it-is-immediate-framing"></a>
- [What it is (immediate framing)](details/project_atomistic_propagator/01-overview_archive.md#what-it-is-immediate-framing)

<a id="locked-decisions--invariants-dont-drift-without-sign-off"></a>
- [Locked decisions / invariants (don't drift without sign-off)](details/project_atomistic_propagator/01-overview_archive.md#locked-decisions--invariants-dont-drift-without-sign-off)

<a id="current-state-2026-07-18"></a>
- [Current state (2026-07-18)](details/project_atomistic_propagator/01-overview_archive.md#current-state-2026-07-18)

<a id="key-entry-points-reuse-dont-rebuild"></a>
- [Key entry points (reuse, don't rebuild)](details/project_atomistic_propagator/01-overview_archive.md#key-entry-points-reuse-dont-rebuild)

<a id="pilot-result-2026-07-18--local-duplex-fluctuation-propagator-loop-closed-end-to-end"></a>
- [Pilot RESULT (2026-07-18) — local duplex-fluctuation propagator loop CLOSED end-to-end](details/project_atomistic_propagator/02-pilot-result-2026-07-18--local-duplex-fluctuation-propagator-loop_archive.md#pilot-result-2026-07-18--local-duplex-fluctuation-propagator-loop-closed-end-to-end)

<a id="literature-verdict-2026-07-18--reframes-the-approach"></a>
- [Literature verdict (2026-07-18) — reframes the approach](details/project_atomistic_propagator/02-pilot-result-2026-07-18--local-duplex-fluctuation-propagator-loop_archive.md#literature-verdict-2026-07-18--reframes-the-approach)

<a id="literature-update-2026-07-19-fresh-search--confirms-the-speed-verdict--finds-the-open-niche"></a>
- [Literature UPDATE (2026-07-19, fresh search) — confirms the speed verdict + finds the open niche](details/project_atomistic_propagator/02-pilot-result-2026-07-18--local-duplex-fluctuation-propagator-loop_archive.md#literature-update-2026-07-19-fresh-search--confirms-the-speed-verdict--finds-the-open-niche)

<a id="revised-direction-supersedes-the-earlier-just-add-a-gnn-handoff"></a>
- [Revised direction (supersedes the earlier "just add a GNN" handoff)](details/project_atomistic_propagator/02-pilot-result-2026-07-18--local-duplex-fluctuation-propagator-loop_archive.md#revised-direction-supersedes-the-earlier-just-add-a-gnn-handoff)

<a id="gnn-speed-benchmark-2026-07-18--the-per-step-speed-verdict"></a>
- [GNN SPEED BENCHMARK (2026-07-18) — the per-step-speed verdict](details/project_atomistic_propagator/02-pilot-result-2026-07-18--local-duplex-fluctuation-propagator-loop_archive.md#gnn-speed-benchmark-2026-07-18--the-per-step-speed-verdict)

<a id="gpu-acceleration-note-user-asked"></a>
- [GPU acceleration note (user asked)](details/project_atomistic_propagator/02-pilot-result-2026-07-18--local-duplex-fluctuation-propagator-loop_archive.md#gpu-acceleration-note-user-asked)

<a id="dev-order-4--autoregressive-rollout-in-progress"></a>
- [Dev-order #4 — autoregressive rollout (IN PROGRESS)](details/project_atomistic_propagator/02-pilot-result-2026-07-18--local-duplex-fluctuation-propagator-loop_archive.md#dev-order-4--autoregressive-rollout-in-progress)

<a id="dev-4-rollout--divergence-diagnosis--fixes-result"></a>
- [Dev-#4 rollout — divergence diagnosis + fixes (RESULT)](details/project_atomistic_propagator/03-dev-4-rollout--divergence-diagnosis--fixes-result_archive.md#dev-4-rollout--divergence-diagnosis--fixes-result)

<a id="known-bug-nadoc-flagged-solvated-psf-fails-in-vmd--fixed-column-parsers"></a>
- [KNOWN BUG (NADOC, flagged): solvated PSF fails in VMD / fixed-column parsers](details/project_atomistic_propagator/03-dev-4-rollout--divergence-diagnosis--fixes-result_archive.md#known-bug-nadoc-flagged-solvated-psf-fails-in-vmd--fixed-column-parsers)

<a id="new-pipeline-modules-this-session"></a>
- [New pipeline modules (this session)](details/project_atomistic_propagator/03-dev-4-rollout--divergence-diagnosis--fixes-result_archive.md#new-pipeline-modules-this-session)

<a id="local-environment-this-machine"></a>
- [Local environment (this machine)](details/project_atomistic_propagator/03-dev-4-rollout--divergence-diagnosis--fixes-result_archive.md#local-environment-this-machine)

<a id="root-cause-of-divergence--stability-strategy-2026-07-19--governs-the-current-plan"></a>
- [ROOT CAUSE OF DIVERGENCE + STABILITY STRATEGY (2026-07-19) — governs the current plan](details/project_atomistic_propagator/03-dev-4-rollout--divergence-diagnosis--fixes-result_archive.md#root-cause-of-divergence--stability-strategy-2026-07-19--governs-the-current-plan)

<a id="data-scaling-study-result-2026-07-19--surprising-more-data-did-not-help-this-regime"></a>
- [DATA-SCALING STUDY RESULT (2026-07-19) — surprising: more data did NOT help (this regime)](details/project_atomistic_propagator/03-dev-4-rollout--divergence-diagnosis--fixes-result_archive.md#data-scaling-study-result-2026-07-19--surprising-more-data-did-not-help-this-regime)

<a id="quick-conservation-test-2026-07-19--path-b-validated-big-result"></a>
- [QUICK CONSERVATION TEST (2026-07-19) — path (b) VALIDATED, big result](details/project_atomistic_propagator/03-dev-4-rollout--divergence-diagnosis--fixes-result_archive.md#quick-conservation-test-2026-07-19--path-b-validated-big-result)

<a id="next-session--start-with-a-then-build-trained-b-user-directive"></a>
- [NEXT SESSION — START WITH (A), then build trained (B) [user directive]](details/project_atomistic_propagator/03-dev-4-rollout--divergence-diagnosis--fixes-result_archive.md#next-session--start-with-a-then-build-trained-b-user-directive)

<a id="new-direction-2026-07-19-a2-solute-focused--learned-energy-engine-local-side-project-no-git"></a>
- [NEW DIRECTION (2026-07-19): A2 solute-focused + learned-energy engine (local side project, no git)](details/project_atomistic_propagator/04-new-direction-2026-07-19-a2-solute-focused--learned-energy-engine_archive.md#new-direction-2026-07-19-a2-solute-focused--learned-energy-engine-local-side-project-no-git)

- [M1d — DELTA-LEARNING (CHARMM baseline + NN) FIXES UNFOLDING (2026-07-19) — continued detail](details/project_atomistic_propagator/04-new-direction-2026-07-19-a2-solute-focused--learned-energy-engine_archive.md)

<a id="m1d--delta-learning-charmm-baseline--nn-fixes-unfolding-2026-07-19"></a>
- [M1d — DELTA-LEARNING (CHARMM baseline + NN) FIXES UNFOLDING (2026-07-19)](details/project_atomistic_propagator/04-new-direction-2026-07-19-a2-solute-focused--learned-energy-engine_archive.md#m1d--delta-learning-charmm-baseline--nn-fixes-unfolding-2026-07-19)

<a id="uncertainty-track-dev-6-started--deep-ensemble-uncertainty-is-calibrated-2026-07-19"></a>
- [UNCERTAINTY TRACK (dev #6) STARTED — deep-ensemble uncertainty is CALIBRATED (2026-07-19)](details/project_atomistic_propagator/04-new-direction-2026-07-19-a2-solute-focused--learned-energy-engine_archive.md#uncertainty-track-dev-6-started--deep-ensemble-uncertainty-is-calibrated-2026-07-19)

<a id="time-to-equilibrate-benchmark--harness-built--validated-on-duplex-2026-07-20"></a>
- [TIME-TO-EQUILIBRATE BENCHMARK — harness BUILT + validated on duplex (2026-07-20)](details/project_atomistic_propagator/05-time-to-equilibrate-benchmark--harness-built--validated-on-duplex_archive.md#time-to-equilibrate-benchmark--harness-built--validated-on-duplex-2026-07-20)

<a id="unified-duplexssdna-correction--seeding-verdict-2026-07-20"></a>
- [UNIFIED duplex+ssDNA correction + SEEDING verdict (2026-07-20)](details/project_atomistic_propagator/05-time-to-equilibrate-benchmark--harness-built--validated-on-duplex_archive.md#unified-duplexssdna-correction--seeding-verdict-2026-07-20)

<a id="ssdna-basic-training--the-blade-relaxer-both-validated-2026-07-20"></a>
- [ssDNA basic training + the BLADE-relaxer both VALIDATED (2026-07-20)](details/project_atomistic_propagator/05-time-to-equilibrate-benchmark--harness-built--validated-on-duplex_archive.md#ssdna-basic-training--the-blade-relaxer-both-validated-2026-07-20)

<a id="blade--the-method-has-a-name--the-curved-origami-test-case-2026-07-19"></a>
- [BLADE — the method has a name + the curved-origami test case (2026-07-19)](details/project_atomistic_propagator/05-time-to-equilibrate-benchmark--harness-built--validated-on-duplex_archive.md#blade--the-method-has-a-name--the-curved-origami-test-case-2026-07-19)

<a id="forcenet--cheaper-nn-27-invariant-measure-preserved-2026-07-19"></a>
- [ForceNet — CHEAPER NN (2.7×), INVARIANT MEASURE PRESERVED (2026-07-19)](details/project_atomistic_propagator/06-forcenet--cheaper-nn-27-invariant-measure-preserved-2026-07-19_archive.md#forcenet--cheaper-nn-27-invariant-measure-preserved-2026-07-19)

<a id="beat-md-lever-exploration-2026-07-19--implicit-solvent-equilibrium-sampling"></a>
- [BEAT-MD LEVER EXPLORATION (2026-07-19) — implicit-solvent equilibrium sampling](details/project_atomistic_propagator/06-forcenet--cheaper-nn-27-invariant-measure-preserved-2026-07-19_archive.md#beat-md-lever-exploration-2026-07-19--implicit-solvent-equilibrium-sampling)

<a id="m3--the-engine-transfers-to-a-crossover-origami-2026-07-19"></a>
- [M3 — THE ENGINE TRANSFERS TO A CROSSOVER ORIGAMI (2026-07-19)](details/project_atomistic_propagator/06-forcenet--cheaper-nn-27-invariant-measure-preserved-2026-07-19_archive.md#m3--the-engine-transfers-to-a-crossover-origami-2026-07-19)

<a id="hardware-acceleration--openmm-cuda-works-on-wsl--9-full-step-2026-07-19"></a>
- [HARDWARE ACCELERATION — OpenMM-CUDA works on WSL → 9× full step (2026-07-19)](details/project_atomistic_propagator/06-forcenet--cheaper-nn-27-invariant-measure-preserved-2026-07-19_archive.md#hardware-acceleration--openmm-cuda-works-on-wsl--9-full-step-2026-07-19)

<a id="m2--gbsa-implicit-solvent-baseline--stable-invariant-measure-2026-07-19"></a>
- [M2 — GBSA IMPLICIT-SOLVENT BASELINE = STABLE INVARIANT MEASURE (2026-07-19)](details/project_atomistic_propagator/06-forcenet--cheaper-nn-27-invariant-measure-preserved-2026-07-19_archive.md#m2--gbsa-implicit-solvent-baseline--stable-invariant-measure-2026-07-19)

<a id="6hb-origami-rung--speed-scaling-verdict-2026-07-19-user-away--autonomous-block"></a>
- [6HB ORIGAMI RUNG + SPEED-SCALING VERDICT (2026-07-19, user away — autonomous block)](details/project_atomistic_propagator/07-6hb-origami-rung--speed-scaling-verdict-2026-07-19-user-away--aut_archive.md#6hb-origami-rung--speed-scaling-verdict-2026-07-19-user-away--autonomous-block)

<a id="handoff--data-scaling-toward-unbounded-stability-current-focus"></a>
- [HANDOFF — DATA-SCALING toward unbounded stability (current focus)](details/project_atomistic_propagator/07-6hb-origami-rung--speed-scaling-verdict-2026-07-19-user-away--aut_archive.md#handoff--data-scaling-toward-unbounded-stability-current-focus)

<a id="process-notes-for-any-session"></a>
- [Process notes for any session](details/project_atomistic_propagator/07-6hb-origami-rung--speed-scaling-verdict-2026-07-19-user-away--aut_archive.md#process-notes-for-any-session)

<a id="open-decisions"></a>
- [Open decisions](details/project_atomistic_propagator/07-6hb-origami-rung--speed-scaling-verdict-2026-07-19-user-away--aut_archive.md#open-decisions)
