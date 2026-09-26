# Fixed cis-anti-I validation protocol, v1

This protocol replaces “launch another fit after the last optimizer finishes.”
The **membership, split and limits are fixed now** in
[`validation_policy_v1.json`](../experiments/cpd_anti_additive/validation_policy_v1.json).
The reference calculations are **not yet basin-qualified**. Missing evidence blocks
fitting; defining this protocol does not retroactively certify the campaign.
This is additive CHARMM fragment qualification, followed by separately authorized
interstrand testing. It does not confer full scientific release.

## Research basis and what we adopt

1. Qiu et al., *Driving torsion scans with wavefront propagation* (2020),
   [paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC7320903/) and
   [author-maintained method documentation](https://torsiondrive.readthedocs.io/en/latest/).
   Multiple starting conformers and propagation from both neighbors reduce the
   path dependence of serial relaxed scans. Revisit neighbors when a lower solution
   arrives; stop only when the propagation queue is exhausted. This supports our
   acquisition strategy, not a proof that every global minimum has been found.
2. Vanommeslaeghe et al., *CHARMM General Force Field* (2010),
   [original protocol](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/).
   Adopt its 0.03 Å bond/3° angle tolerances and emphasis on water-interaction
   targets for charges. For neutral polar sites retain HF interaction-energy
   scaling by 1.16 and the −0.2 Å distance correction. Its ideal water-energy
   agreement is 0.2 kcal/mol; our **prospective practical limit is 0.5**, with
   the ideal score also reported. Preserve deliberate dipole overpolarization
   (1.2–1.5 times the QM magnitude), rather than fitting the unscaled dipole to zero error.
3. [OpenFF independent conformer benchmark](https://openforcefield.org/community/news/general/benchmark-small-molecules/)
   and [Sage benchmarking paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10269353/).
   Use geometry and conformer-energy tests together and keep training exposure
   separate. Relative energies use the same QM-selected reference identity in
   both methods. A minimum-energy envelope and a matched-conformer comparison
   answer different questions; report both rather than substituting one for the other.

The other numerical limits below are **local prospective decisions**, not
universal literature standards or thresholds estimated from our failing candidates.
Their revision requires a new protocol version, preserving the old verdict.
These small fragment tests cannot establish broad chemical transferability.

## Fixed set and exposure

The manifest contains **94 required records**, not 94 new simulation jobs:

| Family | Membership | Role |
|---|---|---|
| Periodic profiles | 12 points per endpoint, original reference angle + offsets −180…150° in 30° increments | 24 development records |
| New angular targets | Each endpoint at offsets ±22.5°, ±67.5°, ±112.5°, ±157.5° | 16 prospective holdouts |
| Existing profiles | All 15 points in the frozen previous MM-profile plan, including remote endpoint 2 | Exposed regression; preserve all old branches |
| Stationary structures | Core; original endpoint 1; original endpoint 2; remote endpoint 2 | Four regression records; unconstrained minimum evidence required |
| Existing water targets | Six sites on three conformers, except the previously identified mixed remote 1:O4 contact | 17 exposed development curves |
| ESP/dipoles | Original endpoints 1/2 and remote endpoint 2 | Three regression records |
| New water orientations | Six sites on endpoint 1 and remote endpoint 2; rotate the existing probe +60° about its target approach axis | 12 prospective holdout curves |
| Export equivalence | Core and both sugar fragments | Three engineering records |

Geometry/graph/angle sources already available are hash-pinned in the manifest.
All previous strengths, midpoint tests, lower-basin checks and current ±15° runs
are **exposed development evidence**, even where old filenames said “held out.”
New angular holdouts measure interpolation to new configurations of the same
fragments; they are not independent molecules. Keep entire water curves together,
never randomly split adjacent distances. New orientations must pass contact
screening before QM. If a registered orientation cannot provide a clean bracketed
site curve, leave it blocked and revise the protocol explicitly; do not select a
replacement after looking at a candidate's error.

No blind targets may be computed/inspected until a single candidate parameter
bundle is locked. A blind failure is consumed validation data. It cannot then be
used for tuning while continuing to claim blind success against v1.

## Basin acquisition and identity

Use the existing tight MP2/6-31G(d) DF frozen-core protocol, response convergence
1e−10, electronic E/D tolerances 1e−12 and geomeTRIC GAU_TIGHT. Reuse a native
result only when coordinates, settings, atom order and hashes agree. Older looser
results stay in the archive; do not silently merge them into a homogeneous surface.

Start each endpoint from all distinct known QM and MM-derived families, including
original, remote, lower-reference and lower−30 conformers where available.
At each grid point retain every stationary branch and its seed lineage. Propagate
improved solutions in **both periodic directions**. For closure, require a final
bidirectional sweep with no energy improvement exceeding 0.05 kcal/mol and no
unresolved required branch. New basins also trigger propagation, even if they
are not the current lowest-energy branch. Do not energy-prune the declared grid.
A failed optimization is unresolved coverage, not a high-energy exclusion.

Each optimization has a 60-gradient cap. One evidence-supported continuation may
add at most 20 new gradients using verified replay. After that, investigate the
failure rather than repeatedly raising budgets. Complete at most two additional
closure sweeps per acquisition review; an active queue then triggers a method/
coverage review, not a claim of convergence. Current jobs remain acquisition work.
This document defines the scheduling rule; the existing pair runner is **not yet
a full TorsionDrive scheduler**. Record and review the propagation queue explicitly.

Basin assignment requires exact atom ordering, graph, stereochemistry, a proper
rotation heavy-atom RMSD ≤0.25 Å and maximum circular difference ≤20° over **all
heavy-atom proper torsions**, including the sugar and CPD rings. Exclude no torsion
because it is inconvenient; exclude only undefined collinear paths with a recorded
reason and complementary ring-pucker evidence. No reflections or endpoint swaps.
These are operational matching tolerances, not a proof of connected basins.
A glycosidic angle alone cannot identify the basin. Compute the descriptor list
from the frozen graph and preserve its hash. `geometry_match` implements the
coordinate comparison; reviewers must verify descriptor coverage and stereo.

Use QM→MM minimization and MM→QM checks for unmatched/new low-energy branches.
An unmatched pair is a basin-transfer failure; do not score its energy as though
it were a matched pair. Also report the lowest observed energy envelope, all branch
populations in the search, and failures. Populations of optimizer starts are not
thermodynamic populations.

After closure, choose the lowest **observed, qualified QM** reference per fragment;
freeze its identity and geometry. Use that same conformer identity for the MM zero:
`ddE_i = (MM_i − MM_ref) − (QM_i − QM_ref)`.
Never re-zero independently per method, candidate, seed, or branch. Discovering a
lower reference later invalidates the dataset lock and requires a versioned review.
Do not claim these potential-energy differences are free energies.

## Acceptance gates

All required cases must be present. No favorable average compensates for a failed
case; no missing result counts as a pass.

| Gate | Required result |
|---|---|
| Native evidence | Hashes, atom map, method, native convergence and stereo all verified; finite data |
| Constrained QM | Projected max/RMS atom gradient ≤1.5e−5/1e−5 au; torsion residual ≤0.01°; basin closure as above |
| Constrained MM | Projected max/RMS ≤5.1e−7/2.1e−7 au; multistarts complete; matched basin |
| Unconstrained minima | Full-gradient stationarity and positive projected Hessian at two finite-difference steps; uncertain soft modes resolved, not waived |
| Geometry | Every relevant bond error ≤0.03 Å, angle error ≤3°; basin descriptors also pass |
| Energies | RMSE ≤1.0 kcal/mol separately for each endpoint and split; every absolute error ≤2.0 kcal/mol, including remote conformers |
| Water | Every clean, bracketed curve: absolute minimum-energy error ≤0.5 kcal/mol and distance error ≤0.2 Å after CHARMM corrections; report fraction within ideal0.2 kcal/mol |
| Electrostatics | Fixed caps/sugar/LJ, neutrality and charge constraints retained; dipole ratio1.2–1.5, direction error≤15°; ESP relative RMSE increase≤0.05 versus frozen baseline on each conformer |
| Export | Complete parameter coverage; energy difference≤1e−5 kcal/mol and force difference≤1e−4 kcal/mol/Å between native MM and CHARMM export |

Dipole direction is ill-defined for vanishing dipoles; v1 assumes these fragments
have finite polar dipoles. If that assumption fails, block and amend the protocol,
not divide by a near-zero magnitude. ESP is a regression diagnostic in the charge
strategy; do not lower water performance to optimize raw ESP alone.

Do at most **two fit rounds per functional model** against development data before
review. Require at least20% reduction in development energy RMSE without worsening
any previously passing hard gate to justify the second round. Freeze a chosen
candidate before one holdout evaluation. A failure then requires model review
(torsion coupling, charge/LJ balance, or adequacy of reference chemistry), not
another strength sweep against the same now-exposed holdout. Round choice and the
20% comparison require a reviewed fit-round ledger; the gate checks the declared
round number, not an optimizer's scientific judgment.

## Enforced workflow and evidence format

`validation_gate.py` is a fail-closed aggregator of **independent native audits**;
it does not invent native validation from service status. Every packet record is
`{"case_id": "...", "review": {"path": "...", "sha256": "..."}}`.
A review contains matching `case_id`, nonempty hash-pinned `artifacts`, `checks`
(boolean verdicts) and `metrics` (finite numbers with units in field names).
The exact required fields are checked in the evaluator. Native audit outputs need
explicit case adapters/review records; unadapted old results stay pending.

Packets include `policy_sha256` and `references`, mapping endpoint strings to
frozen `{id, qm_energy, qm_geometry}` (energy in kcal/mol and a hash-pinned geometry
source). Missing reference identity or geometry blocks acquisition. Candidate packets additionally include a parameter
bundle source, its registration receipt, training IDs, fit round and exposure
statements. Each candidate review must name the same parameter-bundle hash.
For profiles, packet `references` adds `mm_energy` to the same fixed reference records in kcal/mol; every row must use those identical reference energies and
identity. This is checked before recomputing errors. Holdout reviews must attest
target generation after registration and no use in fitting. Evidence attestations
are review obligations, not a cryptographic proof against fabricated inputs.

```bash
# Safe: show missing or failed evidence; does not start simulations.
.venv/bin/python experiments/cpd_anti_additive/validation_gate.py status
# Nonzero exit when required acquisition evidence is missing or fails.
.venv/bin/python experiments/cpd_anti_additive/validation_gate.py check --packet PATH
# Only succeeds with complete acquisition evidence; creates an exclusive lock.
.venv/bin/python experiments/cpd_anti_additive/validation_gate.py freeze --packet PATH
# Lock selected immutable bundle (JSON with hash-pinned artifacts for all FF files).
.venv/bin/python experiments/cpd_anti_additive/validation_gate.py register --parameters BUNDLE
# Candidate acceptance requires all94 records, including holdouts and exports.
.venv/bin/python experiments/cpd_anti_additive/validation_gate.py check --stage candidate --packet PATH
```

The launcher intercepts parameter-fitting commands. Direct joint/bonded and charge
fit entry points also check the dataset lock **before creating output folders**.
After registration, further fitting is blocked to protect the holdout. Native
QM/MM acquisition, audits and watcher continuations remain available. Future
fitting scripts must call the same guard and consume the frozen data/split rather
than introducing ad hoc target selection. The guard does not automatically rewrite
historical fitting objectives. No override flag or “service complete” shortcut.

## DNA and product scope

After fragment qualification, prepare the existing `2hb_1xT_CPD` site as an isolated
review artifact. Product geometry authorization still applies before integration.
Run anti, matched syn and undamaged controls with three seeds each, initially
100ps production pilots and then10ns per replica under the frozen CHARMM solvent,
150mM NaCl and300K setup. Use the existing numerical/stereo checks; record lesion
RMSD, contacts, opening and glycosidic/sugar distributions by replica and time block.
Do not require anti to reproduce syn's structure or suppress opening to pass.
These are preliminary stability checks, not equilibrium convergence or experimental
validation. Keep unresolved structural events and syn's own limitations explicit.
No DNA jobs or new full-grid QM campaign are launched by this policy change.
