# Brief for drafting a pilot research proposal

**Working title:** Multiresolution screening of reversible osmotic actuation in a PEG-supported DNA nanoplatform

**Prepared:** September 11, 2026. **Purpose:** A self-contained briefing to upload to an ordinary ChatGPT session for proposal drafting. Local repository files are not required to understand this document. Simulation results below are preliminary internal results, not published findings.

## Instructions to the proposal-writing session

Write a technically defensible pilot proposal for a collaborator, internal review panel or small compute-funding application. Include an executive summary, hypothesis, specific aims, significance, methods, decision criteria, milestones, risks, deliverables and itemized budget. Explain why a staged pilot is worthwhile without asserting that the device will work.

Use the evidence and assumptions in this brief. Cite the linked primary literature. Distinguish completed work, proposed methods and unresolved questions. Do not invent measured performance, successful validation, available force fields, electrode voltage ranges, transition rates or institutional commitments. Do not claim novelty from an absence of retrieved papers. Leave investigator names, institution, funding mechanism and staffing rates as placeholders. The proposed computing cost excludes personnel and substantial new force-field development.

The key deliverable is a parameter-space map that identifies experimentally plausible candidates for further validation. A negative or unresolved result is a useful outcome if its scope and cause are clear. Do not describe the study as full validation of a gold-electrode actuator.

## 1. Motivation and bounded hypothesis

A DNA origami platform sits above a gold electrode on a grafted layer of polyethylene glycol (PEG). An attractive electrode–tile interaction is intended to lower the platform. Compression increases polymer concentration beneath the platform, generating a steep osmotic restoring pressure. The desired displacement range is approximately **3 nm**.

The intended resistance is predominantly **collective osmotic packing pressure**, rather than stretching individual chains as molecular springs. Chain conformational entropy nevertheless contributes to brush equilibrium and cannot simply be removed from the model.

**Pilot hypothesis:** At least one experimentally plausible combination of PEG chain length, grafting density and screened attraction supports a stable, reversible, approximately single-valued platform-height response across a roughly 3 nm operating interval.

The main risk is abrupt collapse, switching or sticking rather than controlled compression. Three mechanisms must be distinguished:

1. Individual PEG chains populate extended and collapsed/adsorbed conformations.
2. The tile has two competing stable heights or loses mechanical stability as attraction increases.
3. Apparent hysteresis arises from insufficient equilibration or rapid driving rather than a persistent device failure.

A bimodal distribution of individual-chain conformations does **not**, by itself, prove hysteretic tile motion. Conversely, a brush with smoothly changing chain conformations can still permit attraction-induced mechanical instability. The primary decision variables are tile height, stability, fluctuations and reversibility; chain-level measurements explain their origin.

“Approximately linear” is desirable but secondary: a monotonic nonlinear response can potentially be calibrated. The broader device concept originally involved a larger platform, but this pilot deliberately uses a smaller system. No extrapolation to the larger device is automatic.

## 2. Scientific rationale and limits of the analogy

### Osmotic brush physics

For neutral polymers in a good solvent, semidilute scaling predicts approximately

\[
\Pi(c)\propto c^{9/4},\qquad \Pi\sim k_BT/\xi^3,
\]

where c is monomer concentration and ξ is a concentration-dependent correlation length. At fixed number of grafted repeat units per area, average brush concentration scales as c ∝ Nσ/h. Thus an osmotic contribution rising approximately as h^(-9/4) is a useful limiting expectation, not a complete force law for a finite, porous DNA tile.

PEG literature emphasizes that overlap alone is insufficient to establish the scaling regime: pressure should become effectively independent of molecular weight at fixed repeat concentration. This is particularly important for our short N36–N76 chains. The pilot must not enforce a 9/4 exponent during fitting or label every dense state Alexander–de Gennes-like. [1,2]

### Why the reported bimodal collapse is a concern, not a prediction

Published electric-field studies show bimodal chain responses in **polyelectrolyte brushes**, including brushes with charge gradients. Their screening and force mechanisms involve charged monomers. Our intended PEG backbone is neutral, with electric forcing primarily acting on the DNA platform. We must not directly transfer the charged-brush mechanism or assign artificial PEG charges to reproduce it. Neutral PEG may still undergo adsorption-driven rearrangement, solvent-mediated collapse or mechanical compression instabilities. [3,4]

### Multiresolution rationale

mrDNA demonstrates a DNA workflow combining rapid coarse-grained relaxation with refinement and atomistic reconstruction. The proposed PEG project borrows this strategy, not a ready-made PEG implementation. Its two-engine loop is coarse-grained sampling in a modified oxDNA implementation, followed by selected atomistic checks in NAMD and comparison after mapping atomistic coordinates back to coarse variables. mrDNA also illustrates the value of osmotic-pressure-based interaction calibration. [5]

The target is agreement of **finite-temperature ensembles and forces**, not minimum-energy structures. A stable-looking short NAMD trajectory cannot certify equilibrium. Coarse and atomistic models can agree and still disagree with experiment.

## 3. Current technical status: what exists and what does not

### Coarse-grained PEG implementation

An experimental, modified oxDNA engine implements a reconstruction of a temperature-dependent implicit-solvent PEG model associated with Chudoba and colleagues. This is not a claim that standard oxDNA ships with validated PEG–DNA or PEG–gold interactions. One PEG bead represents one ethylene oxide repeat, –CH2CH2O–. The adopted convention is referred to internally as “zero-tail”; force-field convention and implementation hashes are recorded. [6]

N36 and N76 mean 36 and 76 repeat units, respectively: approximately **1.59 and 3.35 kDa**, excluding terminal groups and linkers. N135 is approximately 5.95 kDa.

Completed internal validation findings at 294 K:

- Nine isolated-chain lengths, N9 through N795, passed the existing CPU equilibrium-dimension engineering and sampling checks against the recorded literature reconstruction. Digitized preprint/SI references are used; verification against final-journal numerical reference material remains outstanding.
- N36 GPU results pass the frozen 5% CPU-equivalence and timestep-consistency checks. CPU RMS radius of gyration: 1.3410 nm; GPU at 1 fs: 1.3306 nm; GPU at 2 fs: 1.3437 nm. Conservative SEMs are approximately 0.0090, 0.0139 and 0.0086 nm, respectively. The 1 fs cohort used three 20 ns allocations; the 2 fs cohort required three additional 80 ns allocations.
- The N135/1 fs long-cohort recovery has now **completed**. Its three-origin comparison remains **inconclusive**, with RMS Rg approximately 2.9751 nm, conservative SEM 0.0758 nm and minimum effective sample count approximately 16.8. This is not a GPU validation pass. The failed segment had exceeded a CUDA cell-list occupancy allocation; a separate recovery provisioned capacity for the whole chain, preserving original evidence and the remaining sampling budget.
- The single-chain N135 GPU process was measured at approximately **254 MiB VRAM** on an RTX 3080 Ti. This is not a memory estimate for a complete brush–DNA or atomistic system.

### Dense-solution evidence

Existing dense solutions contain **108 N135 chains = 14,580 PEG beads**. Their NPT Monte Carlo sampler runs on CPUs. Seven states, 1–1,000 kPa, have not met the frozen combined convergence criteria despite exhausting their original production caps.

| Imposed pressure (kPa) | Preliminary sampled concentration (g/L) |
|---:|---:|
| 1 | 2.30 |
| 10 | 17.36 |
| 20 | 28.60 |
| 50 | 51.64 |
| 100 | 74.30 |
| 200 | 108.73 |
| 1,000 | 227.40 |

The estimated N135 overlap concentration is approximately 84 g/L using c* = M/[N_A(4π/3)Rg³] and dilute Rg ≈ 3.04 nm. This is a conventional approximate crossover estimate. The highest state is only about 2.7c*. The apparent exponent between 200 and 1,000 kPa is about 2.18, suggestive of semidilute scaling but **not valid evidence of convergence**: it uses two imposed-pressure states with poorly mixed sampled volumes.

Twenty-seven short diagnostics tested baseline, fourfold larger volume proposals and fourfold larger pivot weights at 1, 100 and 1,000 kPa. All completed; none achieved combined volume/shape convergence. Larger volume proposals improved exploratory volume ESS per worker-hour by about 5.6-fold at 1 kPa, without a corresponding general dense-state improvement. Slow chain rearrangement, not GPU memory, is the immediate bottleneck.

Measured 20,000-sweep N135 dense allocations take approximately 1.2–1.7 hours. Twelve CPU workers showed roughly 2.7-fold aggregate speedup over four workers in matched benchmarks. These rates cannot be transferred directly to grafted brushes or a new sampler.

### Atomistic infrastructure

An isolated NAMD preparation workflow exists for PEG-chain/slab assets, solvation, ions, restraints, staged inputs, manifests and analysis preparation. Software tests and a small synthetic file-pipeline check passed. These do not establish physical validity.

Still required: finalized physical PEG end-group/chain assets, compatible water/ion parameters, a PEG backmapper, verified DNA–PEG cross interactions, a bulk osmotic-pressure protocol and the coupled brush–tile workflow. Existing generic brush infrastructure also contains N45 cases; the six-design pilot below uses only N36/N76.

A published CHARMM ether/PEG parameterization is a candidate starting point, not a justification for mixing arbitrary releases, water models or terminal patches. Force-field refinement is possible within the collaboration, but extensive new parameter development is not included in this compute budget. [7]

## 4. Pilot system and parameters

| Component | Initial choice | Status or qualification |
|---|---|---|
| DNA platform | 2 × 4 square-lattice bundle/platform, 32 bp long | User-specified architecture; exact sequence, crossovers, terminal details and orientation require design verification |
| Desired travel | Approximately 3 nm | User objective; not necessarily the available brush height |
| PEG lengths | N36, N76 | Repeat counts; two molecular weights |
| Grafting densities | Nominal 0.1, 0.3, 0.5 chains/nm² | Proposed screen; verify experimental feasibility and exact realized density |
| Cell | Initially 30 × 30 × 25 nm | Check solvent clearance, lateral escape, periodic images and finite-size effects |
| Temperature | 294 K initially | Matches ongoing bulk validation; later match the experiment |
| Buffer | 150 mM NaCl is an existing atomistic setup starting point | Not a validated operating buffer or guaranteed origami-stability condition; Mg²⁺ needs separate treatment if required |
| Lower boundary | Nonpenetrable plane with grafted neutral PEG | Baseline surrogate for a passivated electrode; not an Au–S chemical model |
| Tile support | Initially lateral restraint and fixed orientation; vertical motion allowed | Later release tilt/flexibility; support mechanics must match eventual device |
| Attraction | Effective screened tile–surface interaction | Amplitude initially not assigned a voltage |
| Adsorption | Zero baseline, then bounded sensitivity variants | Literature/atomistic constraints needed for physical interpretation |

Over a full 30 × 30 nm grafting plane, nominal densities correspond to 90, 270 or 450 chains, or roughly 3,240–34,200 PEG beads across the proposed length/density range. A square-grid builder may round these to realizable lattice counts; report realized values. Only a subset is directly beneath the small tile, so lateral redistribution and edge escape must be measured.

A fully water-filled 30 × 30 × 25 nm volume contains on the order of 750,000 water molecules before accounting for excluded volume: an atomistic system can therefore contain roughly two million or more atoms. This is an order-of-magnitude sizing estimate, not a constructed atom count. A solid slab and PEG reduce water volume. It explains why the NAMD stage is much more expensive than the bead model.

## 5. Work packages and analysis

### WP1 — Bulk validation and implementable screening model

Retain original bulk allocation caps and run separate bounded sampler diagnostics. Check detailed balance, acceptance rates, effective samples and independent-start agreement. Validate grafting, wall forces, tile exclusion and the effective attraction in isolated tests before combined production. Sampling moves must respect permanent grafts and chain connectivity; equilibrium-accelerating moves must not be interpreted as real-time dynamics.

Implement a rigid/semirigid tile baseline before releasing additional mechanical degrees of freedom. Do not regenerate or alter the underlying DNA topology solely to resolve simulation difficulties.

### WP2 — Brush compression free energies

For six brush designs, sample ten tile heights spanning the intended interval and its boundaries, with three independent origins from each of two preparation histories: **360 restrained allocations**. A “history” is an initially compressed or extended preparation, not a separate independent seed count by itself.

Estimate mean normal force and W_brush(h) by restrained sampling/thermodynamic integration or umbrella methods. Choose restraint widths and window spacing from overlap diagnostics; ten windows is a planning allowance, not a fixed adequate discretization. Inspect correlations, effective samples, independent histories and uncertainty in force/free energy. Bias removal and restraint-force sign conventions require verification.

Near a putative transition, use a second collective variable, such as chain extension or surface-contact fraction, if h alone fails to sample the relevant rearrangement. The definition of a “collapsed chain” must be physically motivated and checked for threshold sensitivity.

### WP3 — Effective attraction and stability screening

For a rigid horizontal tile, initially use

\[
U_{drive}(h)=-A\exp(-h/\lambda_D),\quad A>0.
\]

Here A has units of energy and represents an effective attraction strength. The downward force magnitude is A exp(-h/λ_D)/λ_D. For tilted/flexible tiles, a spatially distributed site interaction may be needed; do not reuse the rigid-tile reduction without checking it.

Analyze W_total(h) = W_brush(h) + U_drive(h). A local equilibrium requires W_total′ = 0 and W_total″ > 0. Because U_drive″ is negative, attraction can destroy a stable branch even when the brush itself compresses smoothly. Reweighting in h is justified only when the added potential actually depends on h alone and the sampled brush ensemble covers the relevant states.

Explore screening lengths approximately 0.8, 2 and 4 nm as **illustrative model sensitivities**, not three interchangeable versions of the same buffer. Altering salt may also change DNA interactions, solvent behavior and structural stability. Sweep A broadly enough to bracket useful compression and instability; report results first in force/energy units.

Allocate direct compression/decompression checks for three shortlisted designs, three selected attraction settings, three origins and two directions: **54 runs**. Additional rate comparisons may use the robustness allowance or contingency. Ramps diagnose lag but do not by themselves establish equilibrium hysteresis or physical response times.

### WP4 — Robustness and mechanism discrimination

Allocate **36 runs** to selected finite-size, tilt/flexibility, surface-attraction and preparation-history controls. Prioritize perturbations most likely to change the decision; this is not a complete factorial study.

Measure:

- Tile height distributions, mean height, fluctuations, tilt and deformation.
- Free-energy minima, barriers and loss of stable branches.
- Individual-chain extension, end height and contact distributions.
- PEG density profiles and lateral displacement around tile edges.
- Interchain structure, normal pressure, reversible work and correlations.
- Independent-history agreement and fixed-load relaxation, with confidence intervals.

A mean height alone can conceal switching. Chains within one box are correlated; they are not independent replicas. Finite systems may round transitions. Apparent chain bimodality may reflect spatial heterogeneity under the tile rather than temporal switching.

### WP5 — Selected atomistic tests and feedback

Select a promising smooth regime, a suspected transition and a strongly compressed state. Reconstruct PEG atomic conformations while preserving connectivity, graft identities and coarse coordinates. Sample missing torsions, remove clashes and hydrate, then gradually release mapping restraints. Check geometry and remapping errors. Minimized structures are starting points, not equilibrium evidence.

Proposed allocations:

- **9 bulk controls:** three concentrations × three replicas, initially one selected PEG length. Broader molecular-weight independence remains a follow-up unless the allocation is explicitly reassigned.
- **18 brush–tile trajectories:** three selected conditions × two histories × three origins.
- **36 transition windows:** two selected conditions × six windows × three origins, conditional on identifying a transition worth resolving.

Each gets an initial **20 ns total** allowance, including equilibration. Short trajectories may establish local relaxation or persistent force differences while leaving collective equilibrium unresolved. Additional independent atomistic constructions or altered backmapping torsions should be included among controls; not all atomistic origins should inherit the same coarse-state bias.

Use compatible PEG/water/ion/DNA parameters. Begin with a matched nonadsorbing boundary and mechanical load where appropriate, rather than silently introducing unvalidated gold chemistry. A later realistic gold variant is a sensitivity/validation task, not evidence already available.

For bulk controls, ordinary NAMD total pressure is not PEG osmotic pressure. Implement and validate an appropriate protocol, such as a polymer-selective semipermeable restraint with solvent exchange and a defined reservoir reference. Account for reservoir concentration, salt partitioning if present, finite size and restraint-force normalization. The quoted atomistic box throughput does not automatically include a larger reservoir setup.

Compare atomistic data after remapping to coarse variables. Agreement must concern distributions and forces, not merely visual similarity. If tuning is justified, reserve a concentration or chain length for validation rather than fitting and testing on identical states. A two-engine loop is not automatically an exact hybrid sampler; there is no assumption of detailed balance across arbitrary backmapping/relaxation cycles.

## 6. Decision criteria

Pre-register thresholds before production. The following are **proposed engineering criteria**, not established project requirements:

| Decision | Evidence needed |
|---|---|
| Proceed to physical validation | A stable, approximately single-valued branch spanning ~3 nm; independent histories agree; atomistic checks support force/structure trends; the result survives key model sensitivities |
| Redesign | A useful region exists only for particular PEG lengths, densities, supports or limited attraction strengths |
| No-go for a tested regime | Adequately sampled competing tile states, irreversible adsorption, unacceptable fluctuations or loss of stability persist under plausible parameters |
| Unresolved | Strong dependence on initialization, insufficient barrier sampling, uncertain interactions or inadequate trajectory length prevents discrimination |

A provisional hysteresis tolerance is **0.3 nm over 3 nm travel**. Height precision/noise and intended drive timescale still need experimental requirements; do not invent them. Use the frozen bulk effective-sample and uncertainty principles as a starting point, but define observable-specific criteria for the new brush analysis. Absence of a transition in a short trajectory is not evidence of its absence.

Do not promise physical switching times from accelerated coarse sampling. Free-energy barriers can flag kinetic risk; quantitative rates require validated dynamics or additional kinetic analysis. A pilot no-go applies to the tested regime, not all possible PEG actuators.

## 7. Compute plan and budget

All amounts are **USD**, estimated September 11, 2026. Published reference rental rates: RTX 4090 **$0.74/GPU-hour** and H200 **$4.59/GPU-hour**. Lower advertised “from” prices exist but are not used. Availability, taxes and provider conditions require a fresh quote. [8,9]

Use inexpensive GPUs for coarse screening, H200s for selected NAMD jobs, and existing CPUs for current bulk Monte Carlo. Start with one simulation per GPU. Benchmark concurrency before consolidation: fitting in VRAM does not establish better throughput. H200 has 141 GB VRAM, but its benefit for these workloads must be measured. [10]

Atomistic planning assumption: **50 ns/day per H200**. This is not measured PEG–tile performance. Earlier user experience was 55 ns in about 70 hours for a different ~35 × 35 × 25 nm nanopore system on an RTX 6000 Pro; that observation does not establish an H200 speedup.

Initial hardware request: approximately 8 CPU cores and 32–64 GB host RAM per GPU job, revised upward after construction/benchmarking as needed. Shared CPU resources and storage I/O can limit performance. Coarse wall-time allocations below are budgets, not converted validated simulation times.

| Stage | Simulation count/type | Resource allocation | Estimated cost |
|---|---|---:|---:|
| Bulk sampler diagnostics | 9 replicas × up to 18 h | 162 CPU-worker-h on existing workstation | $0 additional rental |
| Compatibility/throughput checks | Approximately 12 short runs | 24 H200-h | $110 |
| Brush preparations | 6 designs × 3 origins | 18 × 4 h = 72 RTX GPU-h | $53 |
| Compression profiles | 6 × 10 heights × 3 origins × 2 histories | 360 × 8 h = 2,880 RTX GPU-h | $2,131 |
| Attraction/reversibility | 3 designs × 3 settings × 3 origins × 2 directions | 54 × 8 h = 432 RTX GPU-h | $320 |
| Robustness controls | 36 selected allocations | 36 × 8 h = 288 RTX GPU-h | $213 |
| Atomistic bulk controls | 9 × 20 ns | 86.4 H200-h | $397 |
| Atomistic brush/tile | 18 × 20 ns | 172.8 H200-h | $793 |
| Atomistic transition windows | 36 × 20 ns, conditional | 345.6 H200-h | $1,586 |
| Storage/transfers | Selective trajectories and checkpoints | Allowance | $200 |
| Sampling/retry reserve | 30% of unrounded compute subtotal | Conditional | $1,681 |
| **Total** | **468 coarse GPU allocations; 63 atomistic allocations; 9 CPU diagnostics; ~12 benchmark runs** | **3,672 RTX GPU-h + 628.8 H200-h + 162 local CPU-worker-h** | **$7,485** |

Unrounded arithmetic: RTX $2,717.28; H200 $2,886.192; compute subtotal $5,603.472; 30% reserve $1,681.0416; storage $200; total **$7,484.5136**, rounded to $7,485. Individual displayed rows are rounded and can differ slightly from the total. This corrects minor arithmetic/rounding discrepancies in the earlier conversational estimate; the scope is unchanged. Round the requested compute envelope to $7,500–$8,000 rather than implying dollar-level forecasting accuracy.

A planning range of roughly **$6,000–$12,000** allows for uncertain throughput and extra sampling; it is not a statistical confidence interval. Convergence failure or major force-field redevelopment can exceed it. The 36 atomistic transition windows are conditional, not mandatory if coarse screening gives a clear decision.

Release approximately **$3,000** for the first coarse screening/benchmark gate, then authorize atomistic work based on informative selected regimes. Full gold/constant-potential electrochemistry, extensive new parameter fitting, additional molecular-weight series, laboratory work and personnel are excluded. This is a new coupled-actuator pilot scope, not an amount to automatically add to earlier generic PEG development budgets: reconcile overlap before funding.

## 8. Schedule, dependencies and risks

With 24 RTX GPUs, 3,672 GPU-hours correspond to approximately **6.4 days** at full occupancy. With 12 H200s, 628.8 GPU-hours correspond to approximately **2.2 days**. These are allocation arithmetic, not end-to-end turnaround. Allow **2–3 weeks of campaign execution after the workflow is operational**, including dependencies, analysis, selection and restarts.

Development is a separate prerequisite: implement and verify grafting/tile interactions, a usable sampler, PEG backmapping and atomistic osmotic-pressure measurement. A firm labor estimate requires a code/asset review; no staffing hours are established here. Do not claim that funding GPUs alone makes the project immediately executable.

Major risks and responses:

- **Poor mixing:** independent histories, overlapping restrained windows, additional coordinates and bounded extension decisions; label unresolved results honestly.
- **Incorrect coarse interactions:** targeted bulk/atomistic validation and sensitivity analysis; avoid interpreting force-field artifacts as device failure.
- **Short chains outside scaling regime:** measure chain-length dependence; retain empirical EOS behavior instead of forcing asymptotic theory.
- **Artificial force geometry:** compare fixed-orientation and tilting/flexible tile models; test lateral escape and periodic boundaries.
- **Uncertain PEG adsorption/gold chemistry:** baseline nonadsorbing surrogate plus physically constrained sensitivity tests; exact chemistry remains a later gate.
- **Electrostatic approximation:** effective attraction cannot establish electrode voltage or usable electrochemical window. Nonlinear electrostatics, ion correlations, charge regulation, electrode polarization and electrohydrodynamics may change the response.
- **Cost escalation:** benchmark first, stop uninformative allocations, preserve a conditional atomistic stage and record all consumed compute.

Poisson–Boltzmann theory treats ions as continuum densities; it is not “explicit-ion simulation.” A later force calculation may use continuum electrostatics with Maxwell plus ionic osmotic stresses, or explicit ions with a suitable electrode model. This pilot does not resolve that choice. Gold electrochemical limits must be established for the actual buffer, reference electrode and waveform; platinum/TiN windows cannot be substituted.

## 9. Deliverables

1. Reproducible system definitions, model versions, mapping rules, seeds and source/input hashes.
2. A coarse-grained compression/attraction map labeled stable, switching, unstable or unresolved, with uncertainty.
3. Representative chain-level distributions and tile trajectories explaining each observed response.
4. Selected atomistic force/structure comparisons, including disagreements and sampling limitations.
5. An experimentally testable shortlist of PEG length/density/support conditions, specifying which parameters remain effective rather than calibrated.
6. A go/redesign/no-go/unresolved recommendation and the next experiment or simulation that would most reduce uncertainty.

## 10. References and their role

[1] **Osmotic properties of poly(ethylene glycols): quantitative features of brush and bulk scaling laws.** PEG-specific bulk/brush scaling and molecular-weight-independence criterion. https://arxiv.org/abs/cond-mat/0208007 ; journal record https://pubmed.ncbi.nlm.nih.gov/12524288/

[2] **A Phenomenological One-Parameter Equation of State for Osmotic Pressures of PEG and Other Neutral Flexible Polymers in Good Solvents.** Dilute-to-semidilute EOS context. https://pmc.ncbi.nlm.nih.gov/articles/PMC4174303/

[3] **Electrical Chain Rearrangement: What Happens When Polymers in Brushes Have a Charge Gradient?** Charged-brush switching mechanism; not direct evidence for neutral PEG. https://doi.org/10.1021/acs.langmuir.3c03127

[4] **Loops, tails and trains: A simple model for structural transformations of grafted adsorbing neutral polymer brushes.** Neutral-brush adsorption as a distinct route to structural change. https://www.sciencedirect.com/science/article/pii/S0021979710011884

[5] Maffeo C, Aksimentiev A. **MrDNA: a multi-resolution model for predicting the structure and dynamics of DNA systems.** Nucleic Acids Research 48 (2020), 5135–5146. https://doi.org/10.1093/nar/gkaa200

[6] **A temperature-dependent implicit-solvent model of polyethylene glycol in aqueous solution.** Source model for the experimental PEG implementation; distinguish original publication from the local reconstruction. https://arxiv.org/abs/1710.09191

[7] Published CHARMM ether/PEG parameterization candidate, Lee and colleagues (2008), PubMed record: https://pubmed.ncbi.nlm.nih.gov/18456821/ . Verify the complete parameter release, terminal chemistry and compatible solvent before use; this is not a claim of PEG–gold or PEG–DNA validation.

[8] RunPod **AI server cost guide**, published RTX 4090 budget reference: https://www.runpod.io/articles/guides/ai-server-cost . Pricing is time-sensitive.

[9] RunPod **Cloud GPU instances**, H200 budget reference: https://www.runpod.io/product/cloud-gpus . Pricing is time-sensitive.

[10] NVIDIA **H200 specifications**, 141 GB HBM3e: https://www.nvidia.com/en-eu/data-center/h200/

## Suggested prompt to accompany this document

“Using the attached briefing, draft a pilot research proposal for multiresolution screening of a PEG-supported DNA actuator. Lead with the decision we need to make: whether a robust ~3 nm reversible positioning regime exists, rather than assuming a linear actuator will work. Separate preliminary internal evidence from proposed work. Explain the neutral-PEG versus charged-brush distinction, the limitations of a screened effective attraction, the need for equilibrium/free-energy sampling, and how selected NAMD checks challenge the coarse model. Include aims, methods, milestones, explicit decision gates, risks, an itemized approximately $7,500 compute budget and cited literature. State that personnel/development and complete electrode electrochemistry are outside this compute estimate. Do not invent missing investigators, institutions, experimental tolerances or validation results.”
