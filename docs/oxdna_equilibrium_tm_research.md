# Equilibrium Tm research status and next session

The hybrid attempt is closed as inconclusive research. No hybrid workflow is
integrated into the wizard, managed jobs, or production engine. A functioning
experimental CLI was built and tested locally; calling the whole attempt
“unimplemented” would conceal that work. **Production integration, reliable
precision estimation and CPD validation remain unimplemented.**

## Attempt register

| Attempt | Evidence | Disposition |
|---|---|---|
| GPU distance-only, pairing-only and mixed metadynamics → frozen-bias production | Six short campaigns; mixed bias increased brief contacts, persistent starting-state disagreement | Experimental prototype; not promoted |
| Increase mixed-bias training from 2M to 6M and 12M steps per walker | Bias drift decreased; q=0↔q>=6 passages 1/5/4; no q=0↔q=8 round trips; no bracketed Tm | Completed experiment, inconclusive for faster Tm |
| Native bias-force corrections | Finite-difference forces/torques, CPU/CUDA comparisons passed on tested frames | Isolated candidate patches; not deployed |
| Longer production with a fixed trained bias and independent campaign repetition | Proposed only | Not implemented or tested in this follow-up |
| Alternative coordinates, replica exchange, expanded ensembles, alternative adaptive bias schemes | Candidate directions only | Not implemented or benchmarked here |
| Hybrid wizard integration, CPD thermodynamics, transferable bias across designs, ±1 C certification | No supporting convergence evidence | Not implemented; do not advertise |

Detailed results: [pilot](oxdna_hybrid_benchmark.md),
[increased training](oxdna_hybrid_training_benchmark.md), and
[retained metrics](benchmarks/oxdna_hybrid/).

## Cleanup and version control

User-authorized cleanup removed 9,889 regular files totaling 554,338,810 logical
bytes from `.development-artifacts/oxdna-hybrid/`, including raw runs, native
builds, copied source trees, diagnostics and logs. Before deletion, compact
metrics, plots, validation summaries, protocol/input hashes and cleanup inventory
were copied and hash-verified under `docs/benchmarks/oxdna_hybrid/` (about 660 KB
allocated). Diagnostic smoke/pilot results are retained only as labeled historical
checks, not pooled scientific evidence. `cleanup.json` records exactly what was
kept. Saved metrics cannot substitute for raw-data reanalysis.

No live process referenced the removed tree. The application's selected engine,
managed user jobs and original molecular documents were preserved. Older
non-hybrid experiment directories were outside this cleanup scope. Do not use
historical absolute paths in the preserved JSON as live dependencies.

Version-control disposition: commit only these research notes and compact metrics.
Do not commit or push unrelated dirty files. Do not include the local hybrid
prototype, native patches or its tests in this documentation closeout: they depend
on other uncommitted research helpers and have no validated production use yet.
Keep that source available locally for the next session, explicitly experimental.
No remote push is part of this closeout. The next session must inventory local
source and dependencies before deciding what merits a separate research-code
commit. A clean checkout should rely on the committed notes, not assume the local
prototype or deleted binaries are available.

## Copyable prompt for the next session

Work in `/home/jojo/Work/NADOC` on a dedicated scientific research session to find,
implement and benchmark the fastest defensible method for estimating **equilibrium
DNA melting temperature**. You may explore any suitable CPU/GPU sampling,
free-energy, biasing, replica-exchange or other algorithm; do not assume our hybrid
or metadynamics must win. Carry the investigation through actual simulations and
analysis rather than stopping at a proposal.

The practical goal is an 8-bp duplex result in under one hour of total wall time,
including bias learning, equilibration, production and analysis, with an explicitly
defined approximate **95% confidence interval of ±1 C**. Eventually compare designs
and CPD isomers through ΔTm with defensible uncertainty, ideally ±0.5–1 C. Separate
sampling uncertainty from force-field/model error; agreement with experiment is a
separate validation. Absolute and relative Tm uncertainties are not interchangeable.
Do not claim the runtime or precision target if the evidence does not support it.

Start by reading `AGENTS.md`, `CLAUDE.md`, relevant storage/scientific-validation
instructions, `docs/oxdna_equilibrium_tm_research.md`, both linked benchmark
reports and `docs/benchmarks/oxdna_hybrid/`. Inventory the dirty worktree before
editing. Our local `tools/oxdna_hybrid/`, `tools/oxdna_umbrella/`, and
`tools/oxdna_vmmc/` may contain useful **uncommitted research code**. Raw hybrid
runs and isolated engines were deliberately deleted; reconstruct only what is
needed and revalidate native forces before sampling. Do not change the production
engine or wizard just to conduct experiments.

Prior results: four GPU walkers on an RTX 3080 Ti, 8-bp sequence-dependent DNA2,
70 C, 0.3 M salt, approximately 12 mM total strand concentration. Mixed-bias
training budgets 2M/6M/12M steps, then fresh bound/separated starts, 200k fixed
equilibration and 2M fixed production steps per replica, cost 4.11/7.95/13.73 min.
They yielded 1/5/4 zero-to-at-least-six-pair passages, zero complete zero-to-eight
round trips, and initial-state binding-probability gaps 0.994/0.227/0.681. Bias
shape became steadier, but reliable equilibrium sampling did not follow. Earlier
VMMC and GPU umbrella observations should be checked against their actual saved
notes; do not invent missing baseline measurements.

Consult primary literature and current native documentation for competitive
methods. Identify the actual bottleneck: bias learning, association/alignment,
zippering, hidden states, poor overlap, correlated production, or computational
overhead. Treat these as hypotheses to test. Compare a small justified set of
methods using matched physical models, sequences, salt and concentration. Use
fair total wall-time budgets; MD steps and VMMC sweeps are not equivalent units
of sampling. Reuse training across designs only after testing transfer validity.

Run bounded pilots with failure/timeout triggers and recorded seeds, engine hashes,
parameters and stage costs. Avoid wasteful completion polling; arrange completion
and failure reporting. No single initial 8-bp candidate should silently consume
more than an hour; stop/reassess poor performers. Check resource availability and
keep native builds and heavy validations serialized under repository safeguards.

For promising methods, test opposing initial states and independent replicas or
campaigns. Measure macrostate round trips, hidden/mispaired states, overlap,
autocorrelation, reweighting efficiency, stationarity and between-replica agreement.
A trapped trajectory must not get a zero-width uncertainty. Validate confidence
interval calibration with independent references or appropriately longer runs;
account for shared bias training and any repeated-look stopping. Reevaluate the
full temperature-dependent Hamiltonian when required and use the appropriate
finite-size/concentration correction. Never count biased-frame populations as
unbiased equilibrium populations or infer thermodynamic Tm from a heating ramp.

Use existing valid exports for the baseline. Do not change the physical model
just to make sampling faster. Preserve NADOC topology, geometry and complete
construction provenance; any new authored structure must follow the real recorded
command paths and publication guard. CPD extension is a later validation step,
not an assumption about the undamaged duplex result.

Deliver a concise method comparison with total runtime, uncertainty, convergence
failures, reproducible settings and a justified recommendation. Report negative
results plainly. Keep experimental features isolated until validated. At closeout,
retain notes, compact metrics, necessary reusable source and a reproducibility
manifest; remove owned bulk experiment data after deriving and checking summaries,
without touching user designs, managed jobs, deployed engines or unrelated work.
Review the diff and decide explicitly which research changes merit a separate
commit; do not push or include unrelated changes automatically.
