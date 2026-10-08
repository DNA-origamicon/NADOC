---
name: project-exp-predictor
description: Exp simulation tab, bounded NADOC-native shape screening predictor; initial data qualification and CPU-first training plan.
metadata:
  node_type: memory
  type: project
---

# Exp predictor

## Salt / reference-control audit (2026-10-07)

See `docs/exp_local_predictor_results.md` for the Mg correction and live RunPod
control audit. New MgCl2 adds salt after neutralization; old packages unchanged.
Running 24HB0 job8466ccc17eff has6nm bbox padding,12.004nm initial nearest-image
heavy-atom gap; no dynamics yet at inspection. Old extra-base boxes are much
smaller, and total counterion density differs despite similar ion counts.
OPEN ISSUE-62: actual4fs relaxation uses fullElectFrequency2 despite manifest1;
no live settings changed. Early-stopped relaxation is not an equilibrium label.
Require matched unrestrained production and box/salt qualification for publication.

## Expanded-data / neural compute pilot (2026-10-07, later)

User authorized broader origami/extra-base assessment and $3 Runpod pilot. Completed
under `.development-artifacts/exp_expansion_20261007/`; details in the expanded-data
section of `docs/exp_local_predictor_results.md`. Five HC configurations now have
mapped all-atom finite-window labels (6HB0/2×T,24HB0/1/2×T);18HB square is held out,
not an equilibrium-qualified label. All six native/MD atom-order and bond sets match.
Additional24HB extra-T data improves held-out extra-atom regression RMS~10–11%, but
square transfer worsens. Significant confounds: original0×T runs Na-neutralized with
MgCl2, new extra-T runs Mg-counterion;6HB2×T half the length of6HB0×T; close periodic
images in24HB/square; square paired-C1 distortion increases. No new equilibrium
certification. Extra-base mean shapes have~0.10–0.11nm rigid-fit residual vs~0.02–0.03nm
core: use conformational/state-aware targets, not a single coordinate mean as a seed.

Alpine authenticated; A100/H200 maintenance reserved until2026-10-08 06:30MDT.
One4090 rented@$0.74/h, independent exact-pod watchdog+provider expiry, 90.88s total;
~$0.0187 estimated GPU cost, results downloaded, provider absence confirmed. No pods
remain; account invoice not finalized. No local GPU/new MD. Two true neural240-update
bursts:644,614params3.51s;5,177,862params13.07s. Five message-passing blocks, all
covalent/paired edges and8 spatial neighbors/nt, condition/extra-base flags. Training
24HB variants,6HB family held out. Platform only synthetic backward memory benchmark.
Large model:24HB2×T4.71GB allocated,platform8.56GB/11.28GB reserved.4090 24GB is enough.
20k updates~18min (~$0.22 compute);100k~91min, loss/architecture-specific, not convergence
ETAs. Revise next comparable campaign to5–20GPUh (~$4–15), not100–500h. No further spend.
Unconstrained neural all-atom decoder fails geometry (6HB0/2×T35/63piercings), not a
seed or live replacement. Next: constrained decoder/geometry losses and better-qualified
labels. **Live Exp remains strain_atoms_v1.json, checksum unchanged.**

## Current local-model investigation (2026-10-07, isolated)

User requested connectivity-aware regression with geometric constraints, compared
against DeepSNUPI on 6HB,24HB,platform.nadoc. Implemented `exp_local.py` (519
coefficients: global strain prior + graph-local rotations/relative displacements),
`exp_local_constraints.py` (joint rigid nucleotide bond/CHARMM-angle/steric
projection), and optional `exp_local_adapter.py` (all atoms + existing Full frame).
**Live Exp still uses strain_atoms_v1.json. Do not silently promote the candidate.**
The candidate v2 fits in1.55s CPU; no GPU/cloud/new MD. Whole-design-held-out
shape RMS6HB0.460/24HB0.698nm, baseline0.497/0.735. DeepSNUPI+refinement is
0.521/0.848 on raw nodes,0.547/0.907 after transporting native C1-midpoint offsets
with upstream triads (no MD labels). Both conventions retained. Platform has no
NAMD truth; local vs decorated DeepSNUPI disagreement1.466nm. Full node maps
630/3192/6766 with residuals0.0148/0.0168/0.0135nm. Native/MD DNA PSF bonds
match exactly, not just atom identities. Source design hashes verified.

**Geometry qualification failed:** v1 length-only translation projection preserved
rings but worsened angles. v2 improves median angle errors to~3.4deg, preserves
intra-nt distances/chirality and reduces worst overlaps, but introduces6 ring
piercings in24HB and10 inplatform and raises soft-cutoff clash counts. Solvers
hit iteration limits;~60%local edge updates hit0.2nm trust bounds. Keep screening
hypotheses separate from seed-qualified structures. Next: non-crossing/steric
constraints coupled to bond/angle/base-pair geometry, then independent plate-like
MD labels; no extra-base training yet. No software lattice/size gate added.

Evidence/checkpoints/all-atom arrays/Full frames/per-junction atom-bond-ring A/B
reviews: `.development-artifacts/exp_local_20261007/`, especially
`review_angles.html`, `model_angles.json`, `comparison_angles.json`,
`geometry_summary_angles.json`. Protocol/results: `docs/exp_local_predictor_results.md`.
Static figures inspected; no candidate live-app promotion/check claimed.
Official CPU DeepSNUPI default energy refinement took58/332/720s on6/24/platform.
Fixed SNUPI PDB adjacent-negative-coordinate reader bug (ISSUE-59), which silently
lost1194 platform nodes; fixed-width fallback retains legacy whitespace parsing.
Headless adapter end-to-end6/24/platform5.59/29.29/68.57s; all atom coordinates
exactly match evaluation, source designs unchanged.
FAST9976passed90skipped; focused10+3+2passed;main.js delta0. Full suite deferred;
existing unrelated lint F401 in test_cpd_cube_validation_v6.py remains.

## Installed baseline and earlier work

2026-10-07 user scope: native NADOC input, approximate relaxed NAMD shape for
screening and eventual seeds; initially manually limited to basic HC designs.
**No software HC/size/extra-base restriction.** One standard production recipe,
not all temperatures/salts and not replacement trajectories. Supersedes old BLADE
full-dynamics ambitions for this feature.

Exp tab is wired with Run/Stop, progress, opt-in preview. `exp_panel.js` owns UI,
`exp_predictor.py` owns a document-scoped session-only CPU inference lifecycle,
`routes_exp.py` its API. Assembly uses the existing compact simulation projection.
Current CPU model installed at `backend/data/exp/strain_atoms_v1.json`, loaded by
`exp_atomistic.py`; `exp_regression.py` supplies the six-mode basis. Six equivariant vector modes: radial/axial/twist plus end
dependence. User authorized 6HB and 24HB 0×T infrastructure pilot. Predictions now include **all DNA atoms including hydrogens**, generated with the
existing CHARMM/psfgen builder. Fit uses all-atom targets, not just reconstructed
atoms around predicted phosphates. Display applies atom-derived backbone anchors,
ring centers and normals to the existing Full model using NAMD's frame transport;
no points/highlighting. Other representations are excluded; leaving Full,
unchecking, engine/design changes clear the physical preview. No native geometry,
topology, export or NAMD seed changes. No lattice gates.

All-atom revision: 213445/42131 atoms (75952/14965 H) for 24HB/6HB;
128 last-half frames per design; extraction/fit/review15.23s CPU. Leave-one-size-out
all-atom RMS24HB1.076→0.860nm,6HB0.682→0.591nm. Six GLOBAL modes cannot
predict local atomistic equilibration or guarantee bond geometry. No solvent/ions/
protein predictions. Extra-base identity transport retained; training coverage0×T.
Inference24HB6.08s/6HB1.12s CPU, including psfgen construction.
Assembly preview uses frozen external Full geometry and shared scene visibility,
restoring authored assembly on Off.
Artifacts: `.development-artifacts/exp_atoms_20261007/`.

CPU sparse triage sampled 11 jobs. Best large candidates are 24HB 1×T/2×T;
last-half block means differ ~0.58/0.57 nm despite stable Rg. This is uncertainty,
not proof of non-equilibration. Need mapped, unwrapped, protocol-qualified labels
and independent-design evaluation. Pilot labels are explicitly finite late-window
means. Recovered 24HB 0×T workspace snapshot: all 6720 residue sequences verified
against PSF; 6644 mapped P atoms. 6HB immutable snapshot: 1328/1307 respectively.
First/last block differences remain ~0.49/0.46 nm, not equilibrium certification.

Superseded phosphate-only CPU pilot completed in 18 s cold-ish / 2.2 s warm: 256 last-half frames per job,
594917c0d119 (24HB) and 892ad3d12d4f (6HB). Leave-one-size-out RMS:
24HB native1.088→predicted0.865 nm; 6HB0.702→0.604 nm. Combined fit errors are
training errors, never held-out claims. Global modes do not model local crossovers.
Datasets preserve nucleotide keys, topology snapshots and zero extra-base labels
for later feature expansion. See [pilot report](../docs/exp_regression_0xT_results.md).
Actual PSFs show both systems are Na-neutralized + hydrated Mg/Cl, not the newer
Mg-counterion protocol; the 24HB generated protocol_fidelity text is misleading.
Ion counts verified and recorded in the model card. Do not claim current-protocol
accuracy from this pilot.

Local 9950X/32 GB class host is ample for initial streamed analysis and small
regression; GPU occupied and untouched by training. Do not rent hardware before
label qualification. Future neural option: one 24 GB GPU or Alpine aa100 pilot.
Details and exact candidate windows: [Exp assessment](../docs/exp_predictor.md).

All-atom revision checks: FAST9962 passed/90 skipped; frontend7472 passed/1 skipped;
three app checks passed (part movement/colors/pixels/restore, Stop, assembly).
Direct 24HB/6HB atom+Full-frame inference passed; source designs unchanged.
Full suite deferred; smoke refused by active NAMD guard. Changed modules lint
clean; repository lint has pre-existing unused Path in test_cpd_cube_validation_v6.
Browser fixtures/credentials cleaned; reviewed screenshot retained in task artifacts.

Direct DeepSNUPI CPU comparison (2026-10-07): installed isolated Python3.10,
Torch2.0+cpu,PyG2.3.1,RoMa1.3.2 and seven released checkpoints. Official SNUPI
exports exact 6HB topology+sequence graph with no solve;630/630 nodes matched,
0.0148nm mapping residual. Upstream network has7,743,052 parameters vsExp6.
6HB coarse-shape RMS vsNAMD finite-window paired-C1 mean: native0.606nm,
DeepSNUPI ensemble1.518nm (1.24s CPU), +default200-step energy refinement0.521nm
(57.34s CPU), Exp trainedon24HBonly0.497nm. InstalledExp0.484nm is trainingerror.
No broad accuracy claim: one design, approximate node/C1 proxy, recipe mismatch,
unknown upstream training overlap;first/lastMDblock means differ0.367nm.
Do not call Exp a learned local all-atom predictor: allatomloss/output but only
six shared global coefficients, cachedfit0.09s. Next model needs local topology/
sequence-dependent capacity and broader independent-design evaluation.
Evidence/env/scripts/interactive3D: `.development-artifacts/deepsnupi_compare_20261007/`;
full protocol in the Exp pilot report. Upstream no-eval behavior preserved; explicit
eval diagnostic worse and kept separate. No GPU or live app/model changes.
