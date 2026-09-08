# cis-syn TT-CPD force-field provenance and capability decision

Quantitative and human-review acceptance boundaries are defined in
[`photoproduct_parameter_acceptance.md`](photoproduct_parameter_acceptance.md) and the
machine-readable `backend/data/forcefield/photoproduct_parameter_acceptance.json`.

Status as of 2026-09-06: **a gate-neutral cis-syn candidate can be built and run by
real psfgen/NAMD; production simulation chemistry remains unavailable and fail closed
until the real response fit and DNA/solution validation pass**.

## Quantitative authorization policy

Human visual approval is no longer a prerequisite for generated conformers or the cis-syn
d(TpT) boundary compound to enter QM calculations. The authoritative policy is
`backend/data/forcefield/photoproduct_parameter_acceptance.json` version 2.1.0. Automated
receipts pin the policy and every source by SHA-256, recompute graph/chirality/geometry
checks on every use, prohibit reflection, and have no force-field registry effect.

This does not weaken the chemistry release boundary. Only complete fitted
topology/parameter assets that pass held-out QM metrics, exact psfgen audits, staged local
minimization, and a real 2 fs explicit-solvent NAMD smoke may become production-capable.
The Scientific Review viewer remains diagnostic and its earlier approvals are retained as
supporting provenance, not parameter authority.

The registry mutation boundary now enforces the same distinction. `review-gate` may pass
only the hash-pinned chemical-definition identity stage, or mark any stage blocked.
Quantitative stages use `record-metric-gate` and require a complete machine-evidence
envelope whose required checks, passed source audits, current acceptance-policy hash, and
required release-asset hash are revalidated before the registry is changed. An arbitrary
review file or “looks good” decision cannot advance QM, fitting, topology, NAMD, solution,
or final release status.

The all-form assembler no longer aliases every candidate to cis-syn-I. The versioned
family policy `photoproduct_candidate_assembly_policy_v2.json` resolves the exact
registered product and assigns a unique ordered CHARMM patch name to each of the eight
forms. A shared v2 charge-boundary asset pins all eight chemical-definition hashes and
proves the common 28 neutral-base atoms versus two unchanged sugar C1′ boundary atoms on
every load. This is only an atom/charge-conservation contract: each form still requires
its own fitted numerical terms and quantitative validation.

The candidate workflow now has a separate unattended authorization. If its held-out
nonbonded limits, bounded full-rank response-fit selection, workbook audit, and exact
product/reactant PSF audit pass, it may run a model-compound minimization and ordinary-mass
2 fs NAMD smoke automatically. This is an evidence-generating test, not a registry gate or
force-field release. Visual approval is neither required nor accepted as a substitute for
those measurements.

The first end-to-end machinery check used the screened 63-atom cis-syn d(TpT) model and a
deliberately synthetic bonded transform while the real off-equilibrium QM response jobs
continue. Real psfgen conserved all 63 atom identities and the -1 pair charge (to the
declared six-decimal PSF serialization tolerance), added exactly one C5-C5 and one C6-C6
bond, regenerated the expected graph terms, and retained the reviewed impropers. NAMD
then completed 2,000 minimization steps and 1,000 ordinary-mass steps at 2 fs. All 100
saved frames retained all four signed stereocenters. Crosslinks spanned 1.484-1.659 Å,
retained intrabase C5-C6 bonds 1.470-1.654 Å, glycosidic bonds 1.372-1.585 Å, and the
minimum nonbonded heavy-atom covalent-radius ratio was 1.650 (required minimum 0.7).
The Archive report SHA-256 is
`e6ee4f9972112eb153d0978b98cb836d34bc4745dfd49a186dc0dcc05a292811`.
Because its bonded transform is synthetic, this run validates the workflow and topology
mechanics only. The background continuation will repeat the identical audit with the
quantitatively selected real response-fit transform.

RCSB PDB archive inputs (`TTD` CCD and `1N4E`) are distributed under
[CC0 1.0 Universal](https://www.rcsb.org/pages/usage-policy). NADOC pins the exact
download hashes, retains attribution/provenance in generated manifests, and uses these
files only for chemical identity and structural validation—not as parameter authority.

NADOC can persist explicit manual `TT-CPD` / `cis-syn` product intent, but this checkout
does not contain a defensible CHARMM36-compatible lesion patch, matching parameters, or a
validated product-placement template. Product designs therefore cannot enter any NAMD or
legacy simulation/export path. In particular, NADOC does not substitute ordinary thymine
plus two bonds, `extraBonds`, or generic cyclobutane terms.

## Evidence spike

The authoritative [MacKerell CHARMM force-field distribution](https://mackerell.umaryland.edu/charmm_ff.shtml)
was checked using the February 2026 additive archive, `toppar_c36_feb26.tgz` (download
SHA-256 `7d4d21ebdb216a48f600fadee862dc77d369a10d5753150635f35e09c3209e08`). A
case-insensitive archive scan for `cyclobutane`, `thymine dimer`, `cis-syn`, `TTD`, and
`CPD` found no cis-syn thymine-dimer DNA residue, ordered two-residue patch, or lesion
parameter stream. The hits were unrelated uses of the letters CPD and generic CGenFF
cyclobutane model-compound terms. Those terms do not establish lesion charges, DNA
boundary terms, stereochemical impropers, or validation and are not adopted by analogy.

The same official archive does provide CGenFF 5.0 reference chemistry useful for an
independent fit: `1MTH` (1-methyl-thymine), `TTHY` (a tetrahydrofuran-thymine glycosidic
boundary model), `BMDU` (5-methyldihydrouracil), `BH2U` (dihydrouracil), and `CBU`
(cyclobutane). The latter three separate useful evidence about the nonaromatic saturated
thymine ring from four-membered-ring strain. Exact archive and file hashes are recorded
in `backend/data/forcefield/photoproduct_reference_forcefields.json`. These are candidate
atom-type/Lennard-Jones/transferable-term sources only, not a fused TT-CPD model. CGenFF itself warns
against replacing a biomacromolecular force field with CGenFF; NADOC therefore retains
CHARMM36 nucleic acid for DNA and requires the product-site terms to pass the lesion QM
and DNA validation gates.

The force-field archive is a public download and requires neither an account nor `sudo`.
The CGenFF assignment program needs a separate institutional license and the ParamChem
service needs an account. Neither is required for the current independent Psi4 workflow;
if used later, its output will remain an initial guess with penalties, not validation.

The historical [CHARMM forum question about cis-syn thymine-dimer parameters](https://forums-academiccharmm.org/viewtopic.php?t=7458)
also describes the missing atom-type/dihedral problem; it does not supply a validated,
licensed parameter set. No AMBER lesion model was considered compatible evidence.

## Structural references (not parameter authority)

[RCSB 1N4E](https://www.rcsb.org/structure/1N4E) and its
[primary crystal-structure report](https://pmc.ncbi.nlm.nih.gov/articles/PMC138548/) are
appropriate validation references for an intrastrand cis-syn product geometry. The
[PDB Chemical Component Dictionary entry TTD](https://www.rcsb.org/ligand/TTD) establishes
the named component's connectivity and stereochemical reference. Neither source supplies
CHARMM36 atom types, partial charges, bonded constants, nonbonded parameters, or license
to infer them, so neither is automatic parameter authority. Antiparallel interstrand
products require separate placement validation and cannot be validated merely by
reflecting the 1N4E template.

## What must be supplied before enabling simulation

The exact missing requirements are machine-readable in
`backend/data/forcefield/cpd_forcefield_manifest.json`. At minimum, enablement requires a
redistributable ordered patch/topology, product types and charge-conserving charges, every
changed bond/angle/dihedral/improper/nonbonded term, an explicit cis-syn chirality
convention, a reproducibly extracted versioned coordinate template, validation evidence,
and warning-free real psfgen plus NAMD 2 fs integration tests for both adjacent
intrastrand and antiparallel interstrand cases.

The legacy manifest's `available` field is informational and is not an enable switch.
Simulation readiness is derived independently for each ordered product from all nine
registry gates plus existence and hash checks for the topology, loadable parameter
stream, template, audit, validation, license/review, and charge-scope assets. The present
manifest deliberately names no topology, parameter, or template file and no license,
because none has been established.

## Published external candidate and current development decision

Ma and van der Vaart, *J. Chem. Inf. Model.* 2017,
[DOI 10.1021/acs.jcim.7b00215](https://pubs.acs.org/doi/10.1021/acs.jcim.7b00215),
published CGenFF-compatible cis-syn CPD atom types, charges, bonds, angles, dihedrals, and
impropers in PDF supporting information. A later NAMD/OpenMM study reports using those CPD
parameters with CHARMM36. This is strong precedent, but the original machine-readable
topology/parameter stream and exact CGenFF dependency cannot be obtained for the present
work. The PDF tables are retained as comparison evidence, not transcribed into a claimed
production force field.

NADOC will therefore develop an independently reproducible additive CHARMM parameter set
from QM target data and solution validation. The workflow, eight ordered DNA-level
TT-CPD stereoisomers, tool gates, and derived release criteria are documented in
`docs/photoproduct_parameterization_workflow.md` and
`backend/data/forcefield/photoproduct_registry.json`. The legacy cis-syn manifest remains
disabled until the corresponding registry entry passes every gate and names verified
assets.

The local workflow now includes a deterministic reviewed-workbook exporter for the future
asset set. It requires a passed hash-linked workbook audit and writes a two-residue
`PRES`, matching parameter candidate, topology-audit specification, and hashes. The
exporter assigns no values and marks its result gate-neutral; a real psfgen syntax check
passes for a synthetic test bundle, but that is explicitly not chemical validation and
does not change the unavailable status above.

The installed psfgen and CUDA NAMD 3 have also passed a hash-audited signed-improper
convention fixture. Holding bond lengths and angles invariant while reflecting one
substituent changed the ordered improper energy from 1.8638 to 21.8719 kcal/mol. This
proves the engine mechanism needed to enforce a reviewed hand; it is not TT-CPD parameter
evidence and passes no product gate. The archived report SHA-256 is
`5a4a3e51a14d622a67dd114da62227b0688168796f8d8caeec30ccc069b12590`.

CHARMM improper parameter identity requires distinct type signatures when mirror-related
ordered endpoints have different fitted equilibrium values. The candidate workflow uses
the endpoint-2 ring-carbon aliases `CPD5B` and `CPD6B` solely for bonded identity. Each
alias copies its selected source type's mass and Lennard-Jones values exactly and leaves
the fitted atomic charge unchanged. This avoids reordering an improper merely to evade a
type collision; such a middle-atom swap is not an exact signed-torsion transformation and
was rejected when a real NAMD trajectory inverted endpoint 2 C5.

The current fitting representation is executable but deliberately incomplete. Both
candidate type branches are hash-pinned to CGenFF 5.0 / CHARMM36 February 2026 and expose
every missing angle, Urey-Bradley, proper, and four stereochemical-improper coordinate as
an initially zero OpenMM fitting variable. A convention audit caught and corrected a
180-degree mismatch in an auxiliary dihedral reporter before fitting; current fit plans
declare `openmm_namd_four_atom_atan2_v1` and older plans are rejected. Full Cartesian
force/Hessian response matrices retain all 5,886 unique Hessian elements and also preserve
their fully coupled mass-weighted vibrational forms after removing the six rigid-body
directions. At relative SVD threshold 1e-8, the general-carbon and cyclobutane-carbon
single-minimum vibrational matrices have ranks 88/140 and 114/148. Thus a single cis-syn
minimum provably does not identify the
candidate parameter basis. These artifacts remain gate-neutral and
`simulation_ready: false`; the additional stereoisomer/conformer targets and regularized
train/holdout fit are required before any numerical term can enter the reviewed workbook.
An explicit null-space audit further localizes all 52 and 34 projected-Hessian null
directions, respectively, to proper-dihedral groups; after diagnostic gradient/Hessian
stacking those counts are 52 and 33. Angle and stereochemical-improper coordinates do
respond independently at this minimum. This narrows the next evidence
campaign to additional coupled conformers without selecting a Fourier basis by
convenience. A stronger v2 audit now hash-links the bonded fit plan and shows
that every unresolved dihedral group is a cyclic central-bond response. Consequently,
ordinary independent torsion scans are not valid targets here; the remaining evidence
must be stereochemistry-preserving coupled ring-pucker conformers with Cartesian
Hessians. The Archive-only rebuilt audit hashes are
`6b925ea600bcf4481d77e029266968a76b439ccbee2aad354ef84c636487c830` and
`8bc86c5633973a13ee5d74e56f043fb730daca797e64728b79003abbae6eca3c`.
The reusable torsion-job generator independently enforces this distinction: its v2 plan
hash-pins the stable-key molecular graph, and generation fails if the central bond is
cyclic, non-single, absent, or stale. This is a workflow safeguard, not parameter evidence.
The reusable response-campaign builder now requires a disjoint, hash-linked training and
validation partition and reports cumulative parameter-space rank gain as independent
stereoisomer/conformer evidence is added. It does not fit coefficients or change any
registry gate, and full rank alone is explicitly insufficient for release.

The independent canonical cis-syn N-methyl model now has a completed Psi4 1.11
MP2/6-31G(d) geometry and Cartesian Hessian. Its harmonic audit found 102/102 expected
modes, no imaginary frequency, and a 41.5522 cm⁻¹ lowest mode; the Hessian SHA-256 is
`82ee229681d2d93594c08af0e4488bc10ef04a03ba257fd26a5c7df26fc1c3ae`. This is valid
QM target evidence for the capped base lesion, not a force-field release. The associated
target audit explicitly remains `partial_candidate_evidence_boundary_model_required`
because two C1′–N1–C6 angles are absent from the N-methyl model. No registry gate is
silently promoted by this calculation.

The same immutable finite-difference protocol has completed for both trans-syn ordered
model compounds. Trans-syn-I was assembled from 211 independently hash-audited RunPod
gradient records and has no imaginary mode among 102/102 expected modes (lowest mode
38.3675 cm⁻¹; Hessian SHA-256
`7ef8d86a69697308ae99e8895e863c4e898b530831c5ec7d1fad3e0deed4e2de`).
Trans-syn-II was assembled from 211 local records and likewise has no imaginary mode
(lowest mode 45.3664 cm⁻¹; Hessian SHA-256
`c1c1f12d531a486dc2eb1b4669c28fce3325cde1e1be21cf9794d4dc81184764`).
These results establish candidate harmonic minima only. Their noncanonical atom-mapped
chemical definitions remain pending review, so NADOC deliberately rejects attempts to
turn either Hessian into fit targets or a placement template.

All seven noncanonical atom-mapped definition candidates are now collated into the
Archive-contained v7 human-review packet. It verifies the complete candidate/audit hash
chain, compares all four ring-center assignments and syn/anti crosslinks, records the
independent Open Babel identifiers, and includes all available minimum evidence. Each
candidate's ring-coordinate sentinels are now replaced by the exact hash-audited direct
minimum (six forms) or endpoint-exchange-equivalent minimum (cis-syn-II); all four signs
were recomputed, and the candidates remain gate-neutral. The JSON
and Markdown SHA-256 values are
`06f20e5b04ac4ae178a778b17e0cc326fb897d8ae386e8f61e1786a202322782` and
`f8cff65cbef951f4d4fee43006dd15c97c8956bb68cd9ccdc8358b0aebeb8f50`.
The decision fields remain blank: this improves review provenance but does not satisfy
the independent human-review gate.

The registry review operation now rehashes its required asset before accepting any
`passed` decision. For `chemical_definition` it also requires the released schema and an
exact product ID/product/stereochemistry identity, then compares the ordered graph delta
against the registry. A future request with no graph may acquire one only through that
explicit, hash-pinned human review; malformed candidate JSON cannot advance the gate.

The post-review ingestion command is also fail-closed. It accepts only a packet explicitly
marked `human_review_complete`, requires complete time-zone-qualified reviewer decisions,
and reopens the full candidate/independent-audit/hash chain. `APPROVE` must sign an exact
released-schema definition whose ordered endpoints, graph, local connectivity,
stereocenters, coordinates, and model boundary equal the reviewed candidate; a scientific
change is `REVISE` and requires regeneration. Four signed-volume sentinels are recomputed
for each approved release. The output is a gate-neutral audit and never attaches an asset
or changes the registry. A live invocation against the still-blank packet was rejected
before an output file was created.

The coordinate-placement contract is likewise fail-closed on product strain. A released
template must provide parameter-asset-hash-linked length bounds for the exact two added
and two retained ring bonds; candidate templates intentionally leave that section
`parameter_review_required`. Syn and anti ring cycles are derived from their reviewed
graphs, and placement rejects missing coverage or any out-of-range bond rather than using
an assumed universal cyclobutane interval.

Both cis-anti ordered model compounds have now completed the same immutable 211-gradient
protocol. Cis-anti-I ran on a budget-capped A40 Pod, passed all 102 modes with no imaginary
frequency (lowest 56.4732 cm⁻¹), and produced Hessian SHA-256
`aedadc6b163b2385371687ee7c50512f8d02df0c084b3f007b2c80b3e9156d83`.
Cis-anti-II ran locally, passed all 102 modes with no imaginary frequency (lowest
57.2628 cm⁻¹), and produced Hessian SHA-256
`9d306b8e5254c1f06c8be2f4d675b69412f33f391b54ba7bc3037c9b426f50b1`.
The RunPod portion cost USD 0.799 and terminated cleanly. These remain candidate minimum
evidence only: anti connectivity and all four ordered stereocenters still require the
declared chemical-definition review before their Hessians can become fitting authority.

The subsequent trans-anti-I RunPod attempt exposed an operational, not chemical, failure:
its VS Code-owned controller died while pod `001tbe2hngei64` remained provider-reported
`RUNNING` past its requested `terminateAfter`. The pod was explicitly deleted and the
account verified empty. Eight complete gradient/run-record pairs remain valid; incomplete
work contributes no scientific evidence. The reconciled campaign estimate is USD 7.206
of the USD 10 cap. Future photoproduct offloads now fail closed unless an exact-pod
user-systemd watchdog starts successfully; provider expiry is advisory only. This incident
does not change any force-field or stereochemical capability gate.

The pending trans-anti-I and trans-anti-II frequency jobs now each have Archive-local,
hash-identical source geometry and optimized-model parent copies. Their relocation
manifest SHA-256 values are
`9df3cfbac4cec3e7121fc9778c8a6e78017e8172b575b321f03008b374f43200` and
`95094b711dcd1d0ea883f7b2e8f4a22bb96dcba160eaddfa1243353e5f25bc8f`,
respectively. The trans-anti-I Archive plan also contains and revalidates all eight
recovered RunPod task pairs, leaving 203 tasks pending. These storage operations do not
change any chemistry gate.

An endpoint-exchange reuse check was also attempted for the two trans-anti N-methyl
models. It failed closed at its independent-identifier prerequisite because the pinned
Open Babel audit assigns different stereochemical InChIKeys. No geometry or Hessian was
reused; both frequency campaigns remain independent. The equivalence loader now supports
Archive relocation only through a job-local `optimized.xyz` with the exact audit-pinned
hash and records declared/effective paths when an audit does pass.

The local distributed worker now also sets Psi4's process-global PSIO path, not only
QCEngine's task sandbox. Runtime inspection after the change showed new trans-anti-II
workers holding their large DF/MP2 files under the per-task Archive directory and no new
`/tmp/psi.*` files. This prevents low-system-disk exhaustion and records both effective
scratch paths in each new run record; it does not alter any QM input or result.
The first plan-identity checkpoint copied 79 complete trans-anti-II task pairs to the
Archive plan, rejected all partial-state ambiguity, and left 132 pending. Its gate-neutral
report SHA-256 is
`082f64a3c3b555b0af69ca86fd8ed64d9382e5e8a69f8d493e385de19b2e2e79`.
After the editor-recovery audit, a controlled handoff checkpoint raised the durable total
to 92 pairs and left 119 pending. A subsequent validated handoff reached 98 complete
pairs and resumed 113 pending tasks. The live two-worker v4 service now reads its
immutable plan and frequency job from Archive and writes its results, scratch, and process
working-directory housekeeping there; no live scientific artifact depends on `/tmp`.
The 5.45 GiB of pre-fix `/tmp/psi.*` files and the 540 MiB temporary campaign tree were
preserved, rather than deleted, under
`/media/jojo/Archive/NADOC_archive/recovered_system_volume/2026-09-04-vscode-recovery`.
Other inactive NADOC temporary outputs and repository-local Psi4 housekeeping files found
during the same recovery were preserved under that Archive recovery root as well.

The trans-anti-II v4 wrapper completed and assembled all 211 gradients, but its final
audit failed closed on a stale parent `/tmp` path. The trans-anti-I v2 waiter consequently
exited without spawning QM. The auditor now resolves only the hash-identical job-local
Archive provenance copy, and the runner can revalidate an existing assembly after such a
post-assembly failure. This recovery checks every task and assembled artifact hash before
auditing; it never recomputes or silently overwrites evidence. The passed v5 batch-report
SHA-256 is `9917a7abb383c62b6f0e261f68e38f6de908b4b4a1496a65d1da8bd529e38403`.
Trans-anti-II has 102/102 modes, no imaginary modes, a 41.0574 cm^-1 lowest mode, and
Hessian SHA-256
`f83fdf6cf2c4113092cbc7989804b045011129f13ac47b45a4713713f949e67c`.
The independent trans-anti-I v3 batch completed all 211 immutable gradient tasks under
the 11 GiB service memory cap and exited successfully. Independent reopening of every
task pair and assembly record passed. Its minimum has 102/102 modes, zero imaginary
modes, a 40.7600 cm^-1 lowest mode, and Hessian SHA-256
`aede5689303b8368688185302edb3d9bc45fee93416567b76085c74981b42350`.
The frequency-audit and final batch-report SHA-256 values are
`043f68b4ff451a87a2bebea5396ab596424e6fe52fdf6af54630b97c85e8a001` and
`2059f111e559eba663c958a8482dba5fd9f9b8d3e55d85a1ceceb0416b246bed`,
respectively. Its immutable plan, results, scratch, and reports remain under
`/media/jojo/Archive/NADOC_archive`.
The broader ignored NADOC runtime workspace was also checksum-migrated to
`/media/jojo/Archive/NADOC_archive/runtime/workspace` and replaced at its repository path
by a symlink. The local API now writes through that Archive-backed path under
`nadoc-api-archive-workspace.service`; no product gate changes as a result.

All seven independently computed frequency jobs (canonical cis-syn-I, trans-syn-I/II,
cis-anti-I/II, and trans-anti-I/II) now have Archive-local immutable evidence. The jobs
that required relocation contain byte-identical source-geometry and parent-audit copies
without rewriting their immutable QM manifests. A regenerated canonical
Hessian-target bundle resolves only the Archive copy and retains the original declared
path for audit. The cis-syn-I/II endpoint-exchange comparison was also regenerated from
Archive inputs and passed at 9.2894e-6 Å heavy-atom RMSD, 9.3280e-10 hartree energy
difference, and rotation determinant +1. Its new equivalent-Hessian reference maps all 36
stable atoms onto the hash-pinned 108 × 108 source matrix while retaining the source frame;
no mirror, tensor rotation, or interpolation is used. Human-review packet v7 includes
this equivalent-source evidence and all six noncanonical direct minima, and its reviewed
coordinate sentinels resolve directly to those minimum assets. Its JSON and
Markdown SHA-256 values are
`06f20e5b04ac4ae178a778b17e0cc326fb897d8ae386e8f61e1786a202322782` and
`f8cff65cbef951f4d4fee43006dd15c97c8956bb68cd9ccdc8358b0aebeb8f50`.
None of these artifacts passes a
chemistry or force-field gate.

The Help trajectory gate now requires the complete registry entry to be
`simulation_ready`, not merely a passed NAMD smoke test. Its embedded parameter and smoke
report hashes must also match the current registry assets. This prevents an otherwise
well-formed candidate trajectory from being presented as a released model before solution
validation and independent release review.

## Eight DNA-level versus six hydrolysis-product isomers

Taylor, DOI `10.1111/php.13694` (2023), shows that preserving the two ordered
nucleotide attachments produces eight DNA-level classes: I and II members of each
cis/trans and syn/anti combination. Figures S1-S2 assign their ordered C5 configurations.
This is the appropriate catalog for NADOC because stable base keys preserve endpoint and
backbone identity. The publisher supplement was reviewed through the publisher-rendered
PDF; its command-line download returned HTTP 403, so the copyrighted PDF is not
redistributed. Its URL, scope, and download status are recorded in the structural-reference
manifest. The source does not supply C6 atom-mapped structures or force-field terms, and
therefore passes no chemical-definition or parameter gate by itself.

Yang et al., DOI `10.1021/jasms.6c00014`, experimentally separated the six products that
remain after sugar/backbone identity is removed and symmetry collapses the cis-syn and
trans-anti pairs. It is analytical corroboration, not the design-level isomer count.

## Six-product analytical update (2026)

Yang et al., DOI `10.1021/jasms.6c00014`, experimentally separated all six thymidine
photodimer isomers and explicitly distinguishes head-to-head syn products from
head-to-tail anti products. Its Figshare supplement
(`10.1021/jasms.6c00014.s001`, file 63497964) was downloaded outside Git and verified as
SHA-256 `e05d24e83a09520f9284e25bd091d1e3c789c1532f9e29abae50fdf387b8102f` under
CC BY-NC 4.0. The registry now encodes C5-C5/C6-C6 for syn and C5-C6/C6-C5 for anti.
The supplement reports six Gaussian DFT sodium-adduct calculations, but it does not
provide their coordinates or ordered absolute atom assignments. It therefore cannot
serve as a coordinate template or close any pending chemical-definition gate. Exact
metadata and limitations are recorded in
`backend/data/forcefield/photoproduct_structural_references.json`.

## Fixed-geometry derivative provenance (protocol 1.5.0)

Protocol 1.5.0 adds a fail-closed `fixed_geometry_hessian` evidence path for coupled
CPD-ring distortions. Its geometry must be hash-pinned, explicitly human-reviewed,
stereochemistry-preserving, and non-mirrored. The calculation performs no coordinate
optimization and retains both the nonzero analytic gradient and full Cartesian Hessian.
This supports a CHARMM/CGenFF-style force/Hessian objective but supplies or approves no
parameter. A cyclic C5/C6 ring bond is never treated as freely rotatable.

The current cis-syn-I pre-QM evidence is stored under
`/media/jojo/Archive/NADOC_archive`. Candidate-set v3 SHA-256 is
`c90dcf6a16d806df8c4e6a5cc352414342ab43e478cd2e08835ff36058c3044c`; the 36-geometry
n=1–6 rank-screen SHA-256 is
`219da4359b2701944ea54d5013ed6e2311fcc332a6aa9d6aff70523046fef73c`; and the nested
periodicity-comparison SHA-256 is
`e613b718a473a89c575aeda036ffd9160889dbebf6930e0926448a598e545535`.
The comparison selects no model. The four-geometry review packet SHA-256 is
`bd45a05ff7baffc101ea6dc06ff857e3157b0d42bcb86cde32f903f079323722`
and remains `review_required`. These artifacts close no force-field or simulation gate.

The same conformer-preparation boundary now covers all seven noncanonical ordered
TT-CPDs. Each product has a versioned mode-source artifact that revalidates its direct
minimum, except cis-syn-II, whose source uses the previously audited endpoint-exchange
equivalence. In that equivalent case the builder applies only the declared stable-atom
permutation to geometry rows and both Hessian axes; it performs no mirror, spatial
transform, tensor rotation, or interpolation. Every mode source declares
`contains_parameter_targets: false`, so it cannot bypass the unreleased chemical
definition.

Sixteen stereochemistry-preserving candidate geometries were generated per product and
four were deterministically queued for review. Canonical cis-syn-I was rebuilt through
the same mode-source boundary as the seven noncanonical forms, so the comprehensive
Archive review index contains all eight ordered DNA products and 32 conformers, all with
recomputed chirality and geometry checks passed.
Its JSON SHA-256 is
`1c8b46afc04a72af492aec8380a99a9ba9c99b361c96f777c915de1d52e27ca8`; its Markdown
SHA-256 is `bdfdb6c2f3182c580e2ed83617bb4b4e6fdc38eb4a0fe1b4cabf3d1750ed5b1a`.
All review decisions are blank. The index creates no fit target, authorizes no QM work,
and changes no registry gate. Fixed-geometry response calculations remain fail-closed
until a qualified human releases the exact atom-mapped chemical definition and separately
reviews and partitions the selected conformers.

A review-only visualization derived from that exact index is stored at
`photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/coupled-conformer-review-visualization-v1`
on Archive. Its manifest SHA-256 is
`5432b28d1436e313a593dc4d22bf1db5a5cf941af087f9f569a540aa4463f6b6`.
It contains eight PDB files and 32 total static `MODEL` records; the manifest records each
frame's source-XYZ hash and the complete atom-serial-to-stable-key mapping. The files are
explicitly unreviewed structure visualizations, not trajectories, force-field validation,
release evidence, or future Help-menu assets. Their production therefore leaves every
chemistry and simulation gate unchanged.

The companion all-eight decision overlay has SHA-256
`2358994190573dcdb04e35501a1cb1921b19ca2ceb6ad2932a25692d14ffc494`
and is stored as
`photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/coupled-conformer-review-decisions-v1.json`
on Archive. All 32 decision, partition, and note fields and all eight reviewer records are
blank. The overlay references immutable plan and geometry hashes instead of requiring a
reviewer to edit those generated plans in place. Software will materialize new reviewed
plans only after complete human input, timezone-qualified provenance, training/validation
coverage, and full geometry/chirality revalidation. The blank overlay was exercised
against the materializer and failed before creating an output directory, as required.

Large-artifact storage is also fail-closed on this workstation. The common photoproduct
storage guard requires `/media/jojo/Archive` to be a real mounted, writable filesystem
before the CLI, local distributed Hessian/response runners, or RunPod controller may use
`/media/jojo/Archive/NADOC_archive`. This prevents an unmounted Archive path from silently
placing QM or trajectory data on the constrained system disk and does not alter chemistry.

## Noncanonical chemical-definition review ingestion (2026-09-05)

The seven exact minimum-backed noncanonical TT-CPD definitions were approved in the
hash-pinned 3D identity reviewer by Jeffe. The accidental trans-anti-I note was corrected
to `Looks good to me.` without changing its approval or source-geometry hash. The complete
visual-decision overlay has SHA-256
`7e5efed7632131eac6affc73186497f7216a74580004edfe01d5de4350f3bbff`.

The fail-closed visual-definition materializer reopened the v7 packet, all candidate and
minimum evidence, the independent Open Babel audit, the source template, and structural
reference manifest. It recomputed every ordered graph/atom-map comparison and all four
signed-volume sentinels per product. All seven records passed with no unresolved product.
The Archive-resident ingestion audit has SHA-256
`07224c6aeb131c012d010d6ec3748ede25ed4196978aee30d2ff8f0381e31cfa`.

Each exact released-schema definition and the audit were then curated under its own
`backend/data/forcefield/photoproducts/<product-id>/` directory, attached by immutable
relative path/hash, and advanced through only the `chemical_definition` registry gate
under that recorded human decision. Registry SHA-256 after curation is
`fcb239624ad4456767d4677a7c663b52abc4cd525712b9523bba49b36c2ee92b`.
All eight ordered TT-CPDs now have passed chemical definitions and remain pending at
`qm_reference_data`. No charge, atom type, bonded term, topology patch, coordinate
template, or NAMD capability is approved by this transition.

## First quantitative cis-syn-I CHARMM/NAMD candidate (2026-09-05)

All four selected cis-syn-I off-equilibrium campaigns were reassembled from 211/211
immutable Psi4 task pairs apiece. Together with the audited minimum, they provide five
force/full-Cartesian-Hessian datasets and 844 successful fixed-geometry derivative tasks.
No QM task was recomputed during the final fit.

The first unconstrained improper-offset regression was rejected after its real NAMD
trajectory inverted endpoint 2 C5. A second model fixes each ordered stereochemical
improper equilibrium at the atom-mapped QM minimum and fits only nonnegative curvature.
Its 156-column combined training design is full rank. The fit-basis, campaign, and selected
candidate SHA-256 values are respectively
`5b9c9e6183356643e8f655f158af72ec3e46178afbd2e3c331a34a0e55176bac`,
`1bf7a5eace6ebb1cb55b32f903a2d414d0e3d69fd1436140a816cc9a28778400`, and
`e4009df56e9f4e2d9773731c0ced5cccf79c1e363b8c9d719bb3652740564b49`.
The selected ridge coefficient is `1e-4`; held-out gradient and Hessian RMSE are 4.7262
kcal/mol/angstrom and 5.7667 kcal/mol/angstrom-squared. These are recorded diagnostics,
not universal release thresholds.

The candidate uses endpoint-specific `CPD5B` and `CPD6B` bonded identities for the second
base while copying their source CHARMM masses and Lennard-Jones terms exactly. This lets
psfgen select all four ordered, non-mirrored improper definitions without changing atom
count, charge, or nonbonded physics. A real psfgen/static-PSF audit and official NAMD 3.0.2
run completed 2,000 minimization plus 1,000 ordinary-mass dynamics steps at 2 fs. Its
report SHA-256 is
`989b82faaa503581f39bbf894c67bab3eb7c521ec93231d90c2971b4aa36aed7`.
The product has exactly the two intended crosslinks, no removed bonds, 63/63 conserved
atoms, pair charge -1.000004 after six-decimal PSF serialization versus -1.0 reactant,
complete reverse identity, finite energies, and 100/100 chirality-valid frames.

A separate 100 ps stress trajectory retained chirality in 5,000/5,000 frames. Crosslink
distances spanned 1.411--1.796 angstrom and the minimum nonbonded heavy-atom
covalent-radius ratio was 1.606. Its report SHA-256 is
`2617b34374e1e37572a1b9a85659b9afb7165f8849c503a42fb332b554292f19`.
One fitted C5 improper curvature is numerically near zero; the coupled terms retained that
center during this test, but the value remains a transferability/sensitivity concern for
MM-vs-QM and DNA-context validation. No arbitrary lower bound was invented.

NAMD 3.0.x was also found to corrupt memory when an output prefix exceeded its internal
140-byte buffer. Candidate configurations now use short paths relative to the Archive
working directory; scientific inputs and outputs remain on the Archive volume.

These results authorize only a non-released cis-syn-I candidate. The registry remains
fail-closed. MM minima/relative-energy validation, explicit-solvent adjacent-intrastrand
and antiparallel-interstrand DNA tests, and the family-level treatment of the other seven
ordered products are still required before any production simulation or Help trajectory
is labeled simulation-ready.

### Literature comparison disposition and corrected-variant path

A subsequent comparison with the Ma/van der Vaart 2017 supporting tables, 1N4E, 1TTD,
and published explicit-solvent CPD simulations found that candidate v3 is useful as an
engine baseline but should not be promoted unchanged.  Its four ring bonds, four internal
ring angles, and four ring proper occurrences came from exact generic CGenFF
cyclobutane matches rather than the CPD response fit.  In particular, the generic ring
angle equilibrium is 106 degrees, whereas the atom-mapped MP2 minimum is 86.8--88.7
degrees and the Ma/van der Vaart CPD-specific comparison is 89.9379 degrees.  The generic
bond constant is 270 kcal/mol/angstrom-squared versus 137.2818 in that comparison.

The 100 ps candidate-v3 trajectory has C5-C5 minimum/mean/maximum
1.411/1.511/1.622 angstrom and C6-C6 1.539/1.660/1.796 angstrom; 10.22 percent of C6-C6
frames exceed 1.70 angstrom.  The 1N4E chain-B coordinates give 1.510 and 1.542 angstrom,
and the MP2 minimum gives approximately 1.569 angstrom for both new bonds.  C5-C5 is
therefore encouraging, but the asymmetric C6-C6 distribution is a mandatory refit and
sensitivity target.  The charge comparison also remains unresolved: the 14 analogous
atoms differ from the published charge set by 0.1302 e RMS, with a 0.3083 e maximum at
N3, and the current held-out water interaction-energy RMSE of 0.208845 kcal/mol narrowly
misses the preregistered 0.2 target.

No isolated number from the literature is being copied into the force field.  Version
1.0.0 of `photoproduct_bonded_refit_policy.json` instead promotes the complete ring
bond/angle/proper block into the existing coupled force/Hessian fit.  The current
candidate remains byte-for-byte as the parent comparison.  Every exported correction
has a stable variant ID plus parent-manifest, policy, workbook, topology, and parameter
hashes.  Real psfgen and ordinary-mass 2 fs NAMD candidate runs remain available through
the parameterization workflow, while the production registry continues to fail closed.

The expanded release sequence and numeric targets are preregistered in
`photoproduct_parameter_acceptance.json` version 2.1.0.  In addition to the existing hard
topology and chemistry gates, it requires MM-minimum and coupled-response comparison,
strict held-out nonbonded revalidation, and at least three explicit-solvent DNA replicas
for adjacent intrastrand and antiparallel interstrand contexts with matched reactant
controls.  The Ma/van der Vaart supporting tables are retained as an independent
comparison only; the unavailable original topology stream is not reconstructed by
guessing and no redistribution right is inferred beyond the source license.

The next all-form response phase is now prepared rather than merely planned. Each of the
seven noncanonical products has four immutable, quantitatively screened MP2/6-31G(d)
fixed-geometry jobs and a 211-task distributed plan on Archive (28 plans and 5,908 tasks
total). Four independent trans-syn-I services are running the first 844 tasks with bounded
CPU/RAM and restart-on-failure behavior. An enabled user-systemd queue waits for all four
passed trans-syn-I batch reports, then runs the other six products sequentially with four
conformers in parallel. User lingering is enabled, so the work does not depend on VS Code
or an interactive login. The queue is fail-closed on a stale/failed report and produces a
hash inventory only after every queued batch passes. It changes no registry gate by
itself.

## First complete-ring corrected cis-syn-I candidate (2026-09-05)

The correction policy was applied to the existing cis-syn-I response campaign without
altering its immutable parent candidate.  It promoted exactly four cyclobutane-ring
bonds, four internal ring angles, and four ring proper occurrences out of the generic
CGenFF transfer set and into a 166-column coupled fit.  The combined response matrix is
full rank (166/166).  The selected `1e-4` ridge model has held-out gradient and Hessian
RMSE values of 4.6241 kcal/mol/angstrom and 5.7336
kcal/mol/angstrom-squared, respectively.  These are candidate-comparison diagnostics,
not release thresholds.

During export auditing, the first corrected workbook exposed a workflow defect: the
fitted angle transformation contained a Urey--Bradley constant and equilibrium distance,
but candidate assembly copied only the harmonic angle pair.  Assembly now copies or
rejects the complete optional Urey--Bradley pair atomically.  The defective workbook is
retained on Archive as diagnostic evidence and was not used for the engine result below.
The replacement workbook audit passed with SHA-256
`dffa98673bb158a920b405d1f71f7a70beede9383b02aceda83d29521cb2a4b5`.

The exported corrected candidate is identified as `cis-syn-ring-refit-v1-a`.  Its
manifest SHA-256 is
`469b5de4c8f20067ff47383cdd69020cdcb5bd74c46ae872e9d85231a74b6b24`
and records the parent candidate, correction policy, workbook, topology, and parameter
hashes.  A real psfgen build verified exactly the intended C5--C5 and C6--C6 additions,
no removed bonds, 63/63 conserved atoms, -1.0 reactant versus -1.000004 serialized
product pair charge, the expected product impropers, and complete reverse identity.

Official NAMD 3.0.2 then completed 2,000 minimization steps and 50,000 ordinary-mass
dynamics steps at 2 fs (100 ps).  All energy records were finite and all 5,000 saved
frames passed chirality and contact audits.  C5--C5 had minimum/mean/maximum distances of
1.413/1.564/1.704 angstrom; C6--C6 had 1.460/1.582/1.715 angstrom.  The minimum nonbonded
heavy-atom covalent-radius ratio was 1.599.  The complete report is stored below
`fit/cis-syn/ring-refit-v1/engine-smoke-100ps-v1-a/` on Archive and has SHA-256
`3475c8cee6aecd77e848717f95e42bba74fa5f7bbdd8bcaf138f264d918e12dd`.

This demonstrates that a corrected, hash-selected variant can be built and run by real
psfgen/NAMD without replacing the production registry assets.  It does not establish
scientific transferability or production readiness.  Full MM-minimum/relative-energy
comparison, strict nonbonded revalidation, explicit-solvent adjacent-intrastrand and
antiparallel-interstrand replicas with matched reactants, and the corresponding work for
the other seven ordered products remain mandatory.  The ordinary NADOC NAMD package path
therefore remains deliberately fail closed for every TT-CPD.

## Retained-thymine correction and Alpine all-form response campaign (2026-09-06)

The complete-ring OpenMM fitting model was audited against the pinned CHARMM36 nucleic
acid topology.  The earlier skeleton omitted all native residue impropers, even though a
CPD patch should remove only the obsolete `C5 C4 C6 C5M` thymine improper and replace it
with product stereochemistry.  The corrected skeleton now parses the pinned topology and
retains, for both thymines, the planar `C2 N1 N3 O2` and `C4 N3 C5 O4` impropers.  Their
exact constants and source-line provenance are resolved from the pinned CGenFF and
nucleic-acid parameter streams.  The stable `C5M` to model-atom `C7` alias is explicit;
the four product-specific stereochemical impropers remain fitted rather than inferred.

Several Archive-preserved model-form branches were evaluated after that correction.  A
166-coordinate fit retaining Urey--Bradley coordinates for every refitted angle had a
best heavy-atom MM-versus-QM minimum RMSD of 0.213 angstrom across the ordinary ridge
scan.  Because generic CHARMM angle entries often have no Urey--Bradley term, a second
explicit model form omitted those coordinates instead of fitting an underdetermined term
to every angle.  The complete n1--n4 no-Urey--Bradley basis improved the best RMSD to
0.1748 angstrom; increasing the gradient contribution fourfold improved it to 0.1464
angstrom.  Restricted n1--n2 and n1--n3 bases were worse.  No result meets the
preregistered 0.10 angstrom gate.  The largest remaining deviations are concentrated at
the two methyl carbons and O4 atoms, so these branches are diagnostic evidence only and
must not be exported or registered as released parameters.  The next correction is an
iterative geometry-aware optimization, such as a hash-pinned ForceBalance campaign,
rather than relaxing the acceptance threshold.

The current all-form fixed-geometry response campaign was regenerated under acceptance
policy 2.1.0 and completed on Alpine as Slurm array job `32131449_[0-23]`: four accepted
conformers for each of the six products that still required response data, 211 tasks per
case, and 5,064 QCEngine tasks total.  Each case uses one 64-core CPU node.  Immutable
inputs and returned evidence live beneath
`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/` locally and
`/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-policy-2.1.0-v1` on Alpine.
The previously computed trans-syn-I responses were independently hash-reconciled under
policy 2.1.0 and required no recomputation.

The submitted bundle exposed a post-compute orchestration defect: it tried to create the
case receipt before synchronizing the distributed plan into the durable result tree.
Completed array elements therefore report Slurm `FAILED` after their QCEngine records
have already synchronized.  This was not treated as scientific success by assumption.
The collector validated the exact plan hash, all 211 result/run-record pairs, and every
original run-record result hash before materializing each of 24 marked recovery receipts;
it reconstructed no QM result.  All 5,064 pairs were then imported byte-for-byte and all
24 Hessians assembled into passed, gate-neutral fixed-geometry audits.  Together with the
four independently reconciled trans-syn-I batches and four earlier cis-syn-I batches, the
hash-pinned all-form completion receipt covers 32 conformers and 6,752 response tasks.
Future campaign bundles synchronize first.  Production registration remains fail closed
until coupled fitting, all quantitative gates, and the required DNA validation campaigns
pass.

## Geometry-aware cis-syn-I candidate and follow-up QM evidence (2026-09-06)

The versioned geometry-aware continuation candidate at
`fit/cis-syn/ring-refit-v6c-geometry-aware-continuation` passed its preregistered isolated
model geometry/curvature checks without relaxing a threshold.  Its heavy-atom RMSD is
0.04306 angstrom, all four signed stereocenters are retained, and its fitted projected
curvature estimate is positive.  A separate hash-pinned policy and implementation then
re-minimized the actual OpenMM candidate with stricter tolerances and finite-differenced
the full Cartesian Hessian at that minimum.  The audit passed with zero negative
vibrational modes and lowest projected curvature 0.20231.  This establishes a stable
isolated-model basin only; the manifest explicitly records `simulation_ready: false` and
`gate_effect: none`.

The same hash-selected candidate was then transformed into a complete CHARMM workbook,
exported as variant `cis-syn-geometry-refined-v6c-a`, and exercised with real psfgen and
official NAMD 3.0.2.  The topology audit found exactly one C5--C5 and one C6--C6 product
bond, conserved all 63 atoms and the pair charge, retained the expected product types and
four product improper records, and preserved complete reverse identity.  NAMD completed
2,000 minimization steps followed by 50,000 ordinary-mass steps at 2 fs (100 ps).  All
5,000 saved frames retained the four required chirality signs, every reported energy was
finite, the product-ring bonds remained between 1.408 and 1.710 angstrom, and the minimum
nonbonded heavy-atom covalent-radius ratio was 1.622.  The immutable report is
`engine-smoke-100ps-v1/candidate_engine_smoke.json` below that candidate directory.

This is an isolated d(TpT) engine stress test, not an explicit-solvent DNA validation or
a force-field release.  In particular, the fitted C5-centered improper force constants
are numerically negligible (approximately 4.3e-15 and 4.2e-13
kcal/mol/radian-squared), whereas the C6-centered values are 12.97 and 18.11.  The proper
torsion network retained stereochemistry in this test, but no post-hoc improper lower
bound was invented.  Low-energy conformer validation and DNA-context replicas must show
whether this parameter partition is transferable before release.

## Independent water orientations and full d(TpT) campaigns (2026-09-06)

The anti-boundary optimization submission receipt for Slurm job `32152198` records
`slurm_array` as `0-2` because the shared submitter initially hard-coded the three-case
syn range.  The submitted SBATCH file and the live allocation both contain the intended
four tasks `0-3`; no anti product was omitted.  The immutable correction sidecar is
`alpine-qm-anti-boundary-optimization-campaign-v1/submission_correction.json` in the
Archive evidence tree.  The submitter now derives this field from `bundle/cases.tsv`.
The correction sidecar SHA-256 is
`4a063858d18e7ee2f3aacbbcac2f7bce7137db4bd7a1f08491afc8129aaf2fed`.

A second fail-closed handoff now waits on the passed full d(TpT) optimizations and builds
one deterministic multi-shell ESP job per product.  These jobs
use HF/6-31+G(d), the charged-model diffuse-basis rule, 16 threads, 36 GiB of Psi4
memory, and a 40 GiB/four-hour Slurm allocation.  Their inputs retain the passed
optimization audit, stable 63-atom map, ESP grid, and all hashes.  The output campaign is
`alpine-qm-boundary-esp-campaign-v1` in the Archive evidence tree and its remote location
is `/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-esp-v1`.  ESP evidence is
for charge-transfer validation only and cannot release charges, parameters, or NAMD
capability.

The full-boundary completeness audit then identified that canonical cis-syn-I had an
earlier screened 1N4E d(TpT) model and candidate NAMD stress test, but not the same
MP2/6-31+G(d) full-boundary optimization/frequency evidence being collected for the
seven noncanonical ordered forms.  A replacement quantitative input screen was generated
against the current hash-pinned acceptance policy at
`fit/cis-syn/dna-boundary-quantitative-screen-v2/chain-b.json` in the Archive completion
tree.  Its single 63-atom, charge -1 optimization campaign has archive SHA-256
`9ba4f8d74101581b4bb4c21d80c18a02dd7a3ba244bd570f724dca0a052e622d`
and was submitted as Alpine Slurm job `32152784_[0]`.  Both dependent handoffs now wait
for three optimization collections and require exactly all eight ordered TT-CPD product
IDs before building eight-case frequency and ESP arrays.  A third handoff builds 432
full-boundary HF/6-31+G(d) water-interaction calculations: six conventional idealized
CHARMM donor/acceptor directions, each sampled at nine distances, for each of the eight
charge -1 d(TpT) products.  Each product is independently screened for severe non-target
probe clashes before submission, and the charged-model rule disables the neutral-only
energy scaling.  This boundary-water campaign is training/validation evidence, not a
license to weaken the 0.2 kcal/mol idealized-site target or to reinterpret arbitrary
azimuth diagnostics as standard CHARMM fitting sites.  These changes close an
evidence-design asymmetry; they do not change the release status of cis-syn-I.

The original six-site water campaign was challenged with two independently generated
probe orientations. Alternate-plane campaign v2 and explicit +120 degree azimuth campaign
v3 each completed all 324 HF/6-31G(d) points, and their collectors passed every input,
output, and curve hash audit. The Archive collection reports are
`alpine-qm-water-validation-campaign-v2/collection_report.json` and
`alpine-qm-water-validation-campaign-v3/collection_report.json`. The first-generation
charge candidates all failed the alternate-plane energy target (aggregate RMSE
0.505--0.825 kcal/mol). Refitting all sites from the canonical and alternate-plane sets
reduced training energy RMSE to 0.128--0.196 kcal/mol, but every candidate still failed
the untouched +120 degree set at 0.379--0.425 kcal/mol. Distance RMSE passed in every
+120 degree comparison. These failures are retained and do not release a force field.

This result must not be hidden by relaxing the preregistered 0.2 kcal/mol target. It also
does not yet prove that ordinary additive CHARMM parameterization is unacceptable. The
original CGenFF method applies the 0.2 kcal/mol ideal to *idealized hydrogen-bond water
complexes in a variety of chemically selected donor/acceptor orientations*, with less
weight on distance; it is not an all-azimuth isotropic accuracy guarantee
([Vanommeslaeghe et al. 2010](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/)).
Fixed atom-centered additive charges cannot represent all electrostatic anisotropy, while
CHARMM Drude lone-pair sites were introduced specifically to improve that limitation
([Lopes et al. 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4334745/);
[Harder et al. 2006](https://pubs.acs.org/doi/10.1021/ct600180x)). The two rotated
campaigns therefore remain quantitative model-form diagnostics. The next additive-model
decision must combine conventional idealized-site targets with ESP/dipole, conformational,
full-boundary, and condensed-phase/DNA validation; it must not fit the +120 degree results
and then reuse them as validation.

Full 63-atom, charge -1 d(TpT) optimization campaigns are now running on Alpine. Slurm
`32151897_[0-2]` covers cis-syn-II and both trans-syn products, and
`32152198_[0-3]` covers all four anti products. Each task uses MP2/6-31+G(d), 64 CPU cores,
100 GiB of Psi4 memory inside a 110 GiB allocation, and a 24-hour limit. The syn seeds use
one rigid proper product rotation with no reflection. Anti seeds instead hold the audited
28-atom product core fixed while UFF repairs only the sugar/phosphate/cap boundary; UFF is
a pre-QM geometry tool, not parameter authority. Six exact-coordinate anti seeds passed.
Trans-anti-II chain B required a separately policy-pinned SDF-serialization perturbation
of only 0.0000699 angstrom to enter a valid relaxation basin. The unusable chain-D basin
and the exact-coordinate chain-B failure remain excluded. Policies are immutable in
`photoproduct_grafted_boundary_policy_v1.json`,
`photoproduct_flexible_boundary_seed_policy_v1.json`, and
`photoproduct_flexible_boundary_seed_policy_v2.json`.

A dependent eight-product MP2/6-31+G(d) frequency array is implemented and waits for all
three optimization collections. It will be built and submitted only if all optimized
models pass exact identity and chirality audits. Every result remains `simulation_ready: false`
until the full topology, parameter, relative-energy/response, explicit-solvent DNA, and
real 2 fs NAMD validation sequence passes.

An additional Archive-backed service,
`nadoc-cpd-post-boundary-fit-inputs.service`, waits for the passed eight-product frequency
collection. It then builds `alpine-qm-boundary-fit-inputs-v1`, containing one immutable
63-atom model graph and Hessian target bundle per ordered product, followed by a
nonbonded-boundary specification. The latter derives effective native boundary values
from the hash-pinned CHARMM36 `THY`, `DEOX`, `5TER`, and `3TER` records rather than
copying values into code: 35 boundary atoms are fixed at total charge -1 and exactly 28
base atoms remain variables at conserved total charge zero. Ordered products do not
receive an endpoint-exchange charge constraint. The associated policy is
`photoproduct_boundary_nonbonded_policy.json`; its atom types and Lennard-Jones classes
are candidate transfer hypotheses, not parameter authority or a release.

The Psi4 electrostatic-potential convention has also been made explicit. `grid.dat`
coordinates follow the molecule unit (Å in these campaigns), whereas `grid_esp.dat`
potentials are atomic units. Point-charge reconstruction consequently uses
`0.529177210903 / r_angstrom`. This agrees with Psi4's own RESP driver and prevents an
approximately 1.8897-fold electrostatic scaling error in later full-boundary charge fits.

The pending full-boundary ESP campaign is pinned to immutable QM protocol 1.6.0. This
version differs from 1.5.0 only where needed for this evidence path: the same
HF/6-31+G(d) wavefunction now produces both `GRID_ESP` and `DIPOLE`, with the latter
written as a deterministic `NADOC_DIPOLE_AU` marker in Psi4's atomic-unit e·bohr
convention. The collector requires and hash-audits that marker for 1.6.0 jobs while
remaining compatible with older GRID_ESP-only manifests. This adds an independent
whole-molecule charge-fit observable without another QM array; it does not release any
charge set or registry gate.

The downstream boundary charge fitter is now implemented and armed, but cannot execute
until the full-boundary ESP and water collections exist. For every ordered product it
holds all 35 CHARMM36 sugar/phosphate/terminal-cap charges fixed and varies only the 28
registered base atoms. Its policy version 1.1.0 preregisters a 54-member grid spanning ESP,
water-energy, dipole, and native-charge-restraint weights. ESP points are sorted by exact
coordinate and every fifth point is held out; both endpoint H3/O2 water sites train the
fit and both O4 sites remain held out. The charged molecule's dipole is compared at the
same coordinate origin with a scale of 1.0, avoiding an origin-dependent empirical dipole
scaling operation. Selection uses only the held-out normalized score. If no choice passes
charge conservation/change, dipole, ESP-improvement, and water energy/distance metrics,
the best diagnostic is retained and the campaign reports failure rather than weakening a
threshold.

The bonded continuation is likewise armed. Policy
`photoproduct_bonded_refit_policy_v2.json` applies the earlier complete-ring correction
to every ordered TT-CPD while forbidding numerical parameter sharing between products.
For each 63-atom Hessian it builds an exact full-graph CHARMM coverage audit, promotes all
four ring bonds, four ring angles, and four ring propers into the fit basis, retains the
native non-ring DNA terms, fixes the four improper equilibria at their registered QM
basins, and omits optional Urey-Bradley fit coordinates. A separate immutable bonded-fit
policy selects a bounded-ridge smoke candidate using deterministic 20% gradient/Hessian
row holdouts. That holdout diagnoses conditioning within one minimum only; it is not
misrepresented as an independent conformer test. Physical CHARMM transformation and all
four stereochemical signs are mandatory before candidate export.

Candidate assembly policy v3 removes the previous N1-methyl-to-C1' substitution. The new
model already is full d(TpT), so all lesion/glycosidic terms map by identical stable atom
keys. A final unattended handoff attempts real psfgen, 2,000 minimization steps, and
50,000 ordinary-mass NAMD steps at 2 fs for every physical candidate. It continues after
an individual failure and records that path as failed closed. These isolated 100 ps runs
are engine stress tests, not solution validation or released help trajectories.

The next gate-neutral handoff is an explicit-solvent d(TpT) test rather than a production
NADOC package. It requires the matching passed vacuum-smoke hash, adds TIP3P water and
150 mM NaCl with the repository's pinned CHARMM36 water/ion assets, and runs ordinary-mass
NAMD through minimization, 1 fs heating, and 100 ps at 2 fs. The implementation was first
exercised against canonical cis-syn-I candidate v3 in a 3,478-atom neutral PME system.
The short real-engine diagnostic completed all stages; all ten sampled 2 fs frames kept
the registered chirality, crosslinks (1.438--1.704 Å), retained ring bonds
(1.495--1.605 Å), and glycosidic bonds (1.427--1.538 Å), with no audited close contact.
This evidence is stored under Archive `photoproduct_evidence/candidate-solution-smoke-dev/`
and has no registry gate effect. The all-eight 100 ps solution service is armed behind the
new full-boundary vacuum outcomes. Duplex/intrastrand/interstrand contexts remain a
separate required validation layer.

The candidate-context topology builder separately exercises stable NADOC identity without
pretending that an unrefined design pose is safe for dynamics. A real psfgen diagnostic
used two one-thymine inserts on different strands of the reciprocal-crossover fixture.
The keys `__xb__:xo_a:0` and `__xb__:xo_b:0` resolved to `D000:9` and `D001:9` only in
the output audit, never in the design. Candidate cis-syn-I patch `TCPDCS1` produced a
1,086-atom product PSF matching the reactant atom identity/count, conserved the selected
pair charge within the PSF serialization tolerance, added exactly two cross-segment
cyclobutane bonds, regenerated the expected graph terms, and passed all product type and
improper checks. The report deliberately says
`passed_topology_only_not_safe_for_dynamics` and records
`coordinates_product_fitted: false`; its files under Archive
`photoproduct_evidence/candidate-context-topology-dev/` must not be simulated. This proves
that crossover-extra design-to-PSF routing is not the remaining blocker. Safe contextual
coordinate fitting/minimization and subsequent solution sampling are.

The same topology-only diagnostic now also has explicit duplex fixtures. Real psfgen
builds for canonical cis-syn-I passed with adjacent ordinary thymines on one strand and
with an ordinary thymine pair on antiparallel strands. Both preserved product/reactant
atom count and passed the exact graph/type/charge/improper audit. Their evidence is under
`candidate-context-topology-dev/cis-syn-v3-adjacent-intrastrand-v1/` and
`candidate-context-topology-dev/cis-syn-v3-antiparallel-interstrand-v1/` on Archive.
They still contain unfitted coordinates and are not dynamics inputs.

That next coordinate step is now implemented as a separate, still gate-neutral command.
`run-candidate-context-precondition` accepts only a hash-matched 63-atom optimized d(TpT)
minimum, its passed zero-imaginary-mode QM release audit, and the matching candidate
CHARMM files. It applies the QM product base coordinates by a four-anchor proper rotation
(reflection is forbidden), keeps all stable design/atom provenance, builds the full
patched PSF with real psfgen, and locally minimizes the lesion plus two residues on each
side for 10,000 NAMD steps. All other residues carry a 10
kcal/mol/angstrom-squared harmonic restraint. The immutable version-1 policy then
requires all four registered chirality signs, four product-ring bonds, both glycosidic
bonds, all selected-to-flank bonds, an exact nonbonded contact audit, finite energy, and
strict nonlocal displacement limits. A passing report is only a candidate coordinate seed
for explicit-solvent testing; it cannot open any registry or packaging gate. The
all-eight Archive-backed service
`nadoc-cpd-post-boundary-context-preconditions.service` is armed behind the genuine QM
release reports and candidate manifests. It attempts three independently reported
contexts per isomer: crossover-extra/crossover-extra cross-segment routing, adjacent
native intrastrand thymines, and an antiparallel native interstrand pair. Thus one failed
pose cannot be mistaken for a pass or hidden by the other contexts.

Every passing precondition now feeds `run-candidate-context-solution-smoke`. The command
rehashes the candidate, fitted topology, final minimized PDB, and exact endpoint mapping;
adds TIP3P and 150 mM NaCl; then runs real NAMD load, 5,000-step minimization, 5 ps of
1-fs heating, and a 10 ps ordinary-mass 2-fs trajectory. The trajectory audit resolves
the lesion residues from the transient patch plan rather than assuming `D000:1/2`, so it
works across segments while keeping those simulation identities out of the design. All
frames must retain product chirality, ring and glycosidic bonds, and safe nonbonded
contacts. This short run is a crash/geometry smoke only, not equilibrium evidence.

The completed optimization plan now covers eight products, including the separately
submitted canonical cis-syn-I boundary case. Its frequency handoff likewise requires all
eight. A second Archive-backed service,
`nadoc-cpd-post-boundary-qm-release.service`, waits for those frequency results and then
builds one `nadoc.photoproduct-qm-reference-release-audit.v1` per product. The assembler
rehashes the raw audit chain and requires 63 unique stable atoms, charge -1, the exact
registered four-bond product/retained-ring graph, finite optimized energy, all four
chirality sentinels, 183 real vibrational modes, zero imaginary modes, and a finite
189-by-189 Cartesian Hessian. These reports are eligible to support the QM metric gate;
they do not pass any fitting or NAMD gate.

The current cis-syn-I fixed-response conformers lie 18--64 kcal/mol above its QM minimum,
so they do not alone test the acceptance policy's low-energy relative-energy region.  A
new 72-point MP2/cc-pVTZ all-product Alpine campaign, Slurm `32135208_[0-7]`, therefore
uses proper-rotation (never reflection) interpolation at 25% and 50% of each audited mode
displacement plus each exact minimum.  A separate 324-point HF/6-31G(d) water campaign,
Slurm `32134901_[0-5]`, tests the six non-equivalent product minima lacking existing
curves.  Its probe definitions are transferred from the reviewed cis-syn-I protocol by
exact stable atom key, and its geometry builder rejects severe non-target clashes.
cis-syn-II is covered through its already audited endpoint-exchange equivalence rather
than by repeating an electronically identical neutral model calculation.  The water
array completed successfully: its collector verified and parsed all 324 outputs and
produced 36 passed fixed-geometry curve audits.  Its report is
`alpine-qm-water-campaign-v1/collection_report.json` beneath the Archive photoproduct
evidence root.  The relative-energy array and both collectors are Archive-backed,
hash-audited, gate-neutral evidence generation.

The relative-energy array subsequently completed with zero Slurm failures.  Its collector
verified and parsed all 72 MP2/cc-pVTZ outputs.  Each ordered product has five to seven
points in the preregistered at-or-below-12 kcal/mol region; the immutable inventory is
`alpine-qm-relative-energy-campaign-v1/collection_report.json`.  Evaluation of the v6c
cis-syn-I candidate against its seven low-energy points passed both preregistered targets:
0.978 kcal/mol RMSE (target 1.0) and 1.914 kcal/mol maximum absolute error (target 2.0).
The hash-bearing report is `relative-energy-audit-v1.json` beside the v6c candidate.  This
is a fixed-geometry validation and a justified coupled-conformer test; it is not a relaxed
torsion scan and does not address DNA-environment transferability.

The first cross-product nonbonded transfer audit rejected silent reuse of the cis-syn-I
charges.  Across the 36 new curves it produced 0.406 kcal/mol interaction-energy RMSE
against the unchanged 0.2 target, although the 0.076 angstrom distance RMSE passed.  A
six-product joint charge fit improved held-out energy RMSE to 0.218 kcal/mol but still
failed the same target.  Individual trans-syn-I and trans-syn-II fits passed their
held-out endpoint curves at 0.039 and 0.052 kcal/mol respectively.  Anti-family fits that
retained endpoint equivalence failed; a versioned chemistry-aware test that allowed the
ordered anti endpoints distinct charges but withheld O4 also failed its held-out O4
curves.  These outcomes are preserved beneath `alpine-qm-water-campaign-v1/` and remain
gate-neutral.

The failure identifies missing discriminatory nonbonded evidence rather than permission
to relax a threshold.  A second six-product, 324-point Alpine bundle uses alternate water
plane orientations at every O2, O4, and H3 site, retains the same distance grid and QM
method, and passed the non-target clash screen with minimum ratios above 1.764.  It is
stored at `alpine-qm-water-validation-campaign-v2/`. Slurm `32151909_[0-5]` completed all
324 points and the collector passed its import and curve audits. Independent validation
then rejected all four older fixed-LJ charge families, as recorded by
`post-water-validation/post_water_validation_summary.json`; none may be promoted. No
gated software download or `sudo` action was required.

## Prioritized boundary recovery cycle (2026-09-07)

The first 63-atom d(TpT) optimization cycle established that its 24-hour execution model,
not the product catalog, was the immediate bottleneck.  `trans-syn-I` reached all OptKing
convergence criteria, wrote `optimized.xyz`, printed Psi4 1.11's `Final optimized geometry
and variables` section, and exited successfully.  The original runner nevertheless called
it failed because its marker list omitted that valid completion form.  A recovery audit now
requires the raw-output and coordinate hashes, return code zero, clean Psi4 exit, all 63
stable atom identities, and all four registered signed-volume stereocenters.  It classifies
that result as `recovered_completed_unreviewed`; it does not release parameters.

The next runnable cycle is governed by immutable policy
`photoproduct_qm_cycle_policy_v2.0.1.json`.  Version 2.0.0's initial 110 GiB Slurm request
was rejected before submission because Alpine's `mem-long` QoS requires at least 240 GiB;
version 2.0.1 changes only that allocation and preserves the rejected bundle as evidence.
All eight ordered DNA product identities and
their product-specific patch/improper orientations remain in the catalog, but eight
independent parameter fits are no longer assumed.  The first wave recovers `trans-syn-I`,
runs the principal `cis-syn-I`, restarts nearly converged `cis-syn-II` from the last complete
hash-pinned geometry, and uses `cis-anti-I` as the anti-family optimizer pilot.  The
`trans-anti-I` pre-instability restart is second-wave work.  The II and remaining anti
full-boundary jobs are deferred unless a named held-out transfer test demonstrates that a
syn-family or anti-family shared term block is insufficient.  No numerical sharing is
authorized without stable term-scope equivalence, product-specific chirality checks,
held-out energy/response tests, and an explicit-solvent NAMD audit for each released
identity.

Protocol 1.7.0 retains MP2/6-31+G(d), density fitting, frozen core, and `gau_tight` for the
charged boundary model.  It adds only registered OptKing trust-step limits
`intrafrag_step_limit 0.1` and `intrafrag_step_limit_max 0.25`, following Psi4 recovery
guidance for `Maximum dynamic_level reached`.  The options were accepted by the pinned
Alpine Psi4 1.11 installation before submission.  The recovery runner uses 32 threads,
100 GiB of Psi4 memory in a 240 GiB `amem`/`mem-long` allocation, a 72-hour limit, a
ten-minute checkpoint extractor, periodic durable result copies, and a ten-minute
pre-timeout signal.  Durable campaign inputs, receipts, and collected results reside on
the Archive drive; Alpine `$SLURM_SCRATCH` is compute workspace only.

The former transient services that required all eight minima and would then launch eight
full Hessians/charge/bonded/smoke continuations were stopped, without deleting their unit
definitions or logs.  That prevents stale automation from spending compute or implying
that product count is parameter-count evidence.  Downstream expansion is now fail-closed
behind the quantitative family-transfer decisions in the new policy.
