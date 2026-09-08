# Photoproduct scientific review checklist

This checklist separates human scientific decisions from reproducible software audits.
Completing it does not itself enable a product: the signed review record, reviewed asset,
and every predecessor gate must still be attached through
`scripts/photoproduct_workflow.py`.

## Current review handoff

Three gate-neutral review stages are available from **Help → TT-CPD Scientific Review**.
The viewer now renders the exact 12-atom local coordinates stored in each minimum-backed
definition, not the earlier initial RDKit embedding. Decisions made against that earlier
embedding are retained but displayed as `STALE` and cannot be ingested. The **Next
unresolved** button and stage counter identify the remaining work.

The authoritative artifacts and all
referenced structures live beneath `/media/jojo/Archive/NADOC_archive`:

- the seven-noncanonical chemical-definition packet is
  `photoproduct_evidence/tt-cpd-definition-human-review-packet-v7/definition_review_packet.json`
  (SHA-256
  `06f20e5b04ac4ae178a778b17e0cc326fb897d8ae386e8f61e1786a202322782`); and
- the all-eight coupled-conformer index is
  `photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/coupled-conformer-review-index-v2/coupled_conformer_review_index.json`
  (SHA-256
  `1c8b46afc04a72af492aec8380a99a9ba9c99b361c96f777c915de1d52e27ca8`).

The DNA-boundary stage shows both 63-atom 1N4E-derived d(TpT) candidates (chains B and
D). Green highlights identify the terminal O5′–H/O3′–H caps, orange highlights identify
the phosphate boundary, purple highlights identify both glycosidic bonds, and the CPD
ring retains the magenta/gold definition colors. These visual decisions remain separate
from definition and coupled-conformer decisions.

The corresponding viewer-friendly, review-only PDB bundle is
`photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/coupled-conformer-review-visualization-v1`
(manifest SHA-256
`5432b28d1436e313a593dc4d22bf1db5a5cf941af087f9f569a540aa4463f6b6`).
It has one four-model PDB per product and an explicit atom-serial-to-stable-key map. These
PDB models are convenience renderings of the same indexed XYZ coordinates—not molecular
dynamics trajectories, parameter evidence, or Help-menu assets.

Record conformer decisions in the concise overlay
`photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/coupled-conformer-review-decisions-v1.json`
(SHA-256
`2358994190573dcdb04e35501a1cb1921b19ca2ceb6ad2932a25692d14ffc494`)
rather than editing the generated plans. This preserves the immutable review sources.

The first review establishes the ordered atom-mapped chemical identities. The second
chooses or rejects off-minimum fitting geometries and assigns accepted structures to
training or validation. Approval of one does not imply approval of the other. Neither
packet authorizes QM, attaches an asset, or changes a registry gate.

## Chemical definition

For each ordered product, a reviewer with small-molecule stereochemistry experience must
record all of the following:

- product name and ordered endpoint convention match the cited primary source;
- every precursor atom maps once to the product and atom/formal-charge conservation is
  explicit;
- syn products add C5(1)-C5(2) and C6(1)-C6(2), while anti products add
  C5(1)-C6(2) and C6(1)-C5(2), with both intrabase C5-C6 bonds retained as single bonds;
- all four C5/C6 absolute configurations are checked atom-by-atom against the cited
  convention, including the Roman-numeral assignment;
- protonation, tautomer, and ordered sugar attachments are explicit;
- RDKit generation and Open Babel cross-check records resolve to the intended graph and
  stereoisomer; and
- supported DNA contexts are claims backed by evidence, not copied from a related form.

The seven generated `chemical-definition-candidate` records intentionally fail the
runtime loader until this review is complete. Their embedded charge scopes carry only an
atom-conservation boundary and approve no transferred charge or parameter.

After all seven current exact-geometry decisions are complete, materialize and audit them
without hand-editing JSON:

```bash
uv run python scripts/photoproduct_workflow.py \
  --storage-root /media/jojo/Archive/NADOC_archive \
  ingest-visual-definition-review \
  --packet /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-definition-human-review-packet-v7/definition_review_packet.json \
  --visual-decisions /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-human-visual-review-v1/visual_review_decisions.json \
  --source-asset-template backend/data/forcefield/photoproducts/tt-cpd-cis-syn/chemical_definition.json \
  --structural-reference-manifest backend/data/forcefield/photoproduct_structural_references.json \
  --output-dir /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-definition-review-ingestion-v1
```

For noncanonical stereochemistry, the materializer embeds and hashes the Taylor 2023
citation record. The hash covers NADOC's citation metadata, not the publisher article;
the article is not redistributed and its publisher terms are not represented as an open
content license. RCSB TTD remains a graph/structural reference, not noncanonical
parameter or stereoisomer authority.

The materializer creates a completed packet. An `APPROVE` decision hashes the exact
released-schema definition; `REJECT` or `REVISE` hashes a separate evidence file. It
fails if a decision's geometry hash is stale. A correction to any
ordered endpoint, atom map, graph bond, signed stereocenter, or source coordinate is a
revision and requires regenerated candidate evidence and a new packet. The ingestion
audit must pass before any file is curated or attached, and the audit itself has no gate
effect.

## Coupled conformers

For each of the eight products, inspect the four XYZ structures referenced by its
`coupled_conformer_review.json`. The deterministic queue contains both signs of each of
the two minimum modes with the largest active-ring fraction at the largest generated
displacement. That is a review workload policy, not evidence that a structure is suitable.
The matching `*.review-models.pdb` can be opened in VMD, ChimeraX, or PyMOL and stepped
through by PDB model number; use the manifest to resolve every displayed atom back to its
stable key and the original hash-pinned XYZ.

For every conformer, the reviewer must:

- inspect the CPD ring, both methyl caps, and carbonyl/nonbonded contacts in a molecular
  viewer with the hash-pinned graph loaded;
- independently confirm that no reflection, atom exchange, ring inversion, broken graph
  bond, nonbonded collision, or chemically irrelevant near-rigid displacement occurred;
- set `review_decision` to `accepted` or `rejected` and provide nonempty
  `review_notes` explaining the coupled distortion;
- assign each accepted structure to exactly `training` or `validation`; and
- retain at least one accepted training and one accepted validation structure per product.

After completing every structure in the UI, materialize and audit fresh reviewed plans
before generating any fixed-geometry job. The ingestion command requires all 32 current
decisions, rejects every `REVISE`, verifies each geometry hash, and requires at least one
training and one validation approval per product:

```bash
uv run python scripts/photoproduct_workflow.py \
  --storage-root /media/jojo/Archive/NADOC_archive \
  ingest-visual-conformer-review \
  --review-index \
    /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1-completions/fit/all-forms/coupled-conformer-review-index-v2/coupled_conformer_review_index.json \
  --visual-decisions \
    /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-human-visual-review-v1/visual_review_decisions.json \
  --product-id tt-cpd-cis-syn \
  --output-dir \
    /media/jojo/Archive/NADOC_archive/path/to/materialized-conformer-reviews
```

Repeat `--product-id` or omit it to ingest all eight products. A product-scoped run is
useful for bringing the canonical cis-syn fit forward first; it does not waive the other
products' reviews or the all-eight final release requirements.

The materializer emits one reviewed plan and one audit receipt per product without
modifying the source plans. The receipts have no gate effect and are not substituted for
the reviewed plans; QM job generation reopens and revalidates the selected plan. For a
noncanonical product,
that generator also requires the separately released chemical definition to reproduce
the reviewed ordered stereocenters exactly. A reviewed conformer plan therefore cannot
bypass a pending chemical-definition gate.

## DNA boundary model

Before running a boundary-model QM job, review:

- cap identities and valences at both 5′ and 3′ ends;
- the −1 dinucleotide charge and phosphodiester protonation state;
- phosphate resonance serialization (no artificial phosphorus stereocenter);
- ordered endpoint and atom names against the chemical definition;
- absence of accidental bond-order changes or added/removed atoms; and
- whether the model actually spans every sugar-, glycosidic-, and phosphate-coupled term
  claimed for fitting.

RCSB 1N4E validates only the adjacent intrastrand cis-syn geometry. It cannot be mirrored
or reused as an interstrand, anti, or noncanonical stereoisomer template.

After approval, bind the exact decision to the selected candidate before generating a
fresh QM job:

```bash
uv run python scripts/photoproduct_workflow.py \
  --storage-root /media/jojo/Archive/NADOC_archive \
  ingest-visual-boundary-review \
  --candidate-manifest \
    /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1/models/dtpdt-boundary-candidate-v2/candidate_manifest.json \
  --visual-decisions \
    /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-human-visual-review-v1/visual_review_decisions.json \
  --output \
    /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-work-v1-completions/reviewed-boundary/chain-b.json
```

The Psi4 runner rejects jobs whose boundary evidence status is still
`candidate_pending_cap_review`; only a freshly generated job tied to
`human_cap_review_complete` can execute.

## Parameter fit

The reviewer must verify that:

- the exact QM protocol, raw outputs, target extraction, train/test split, optimizer,
  convergence, and hashes are retained;
- pair charge is exactly conserved and endpoint symmetry is imposed only after a graph
  automorphism audit;
- existing CHARMM terms are reused only after exact/wildcard type matching and chemical
  transferability review;
- every unmatched bond, angle, Urey-Bradley, proper, improper, and nonbonded term is
  fitted or explicitly justified;
- no AMBER term, generic cyclobutane value, CGenFF penalty score, or two-bond restraint is
  presented as a complete CHARMM36 lesion model; and
- held-out conformers, modes, water interactions, ESP, and condensed-phase tests pass the
  predeclared tolerances.

Before exporting the reviewed workbook, also verify that every bonded record explicitly
states whether it is emitted or reused; every non-CHARMM36 type has a sourced mass and
Lennard-Jones definition; C5/C6 no longer use the reactant THY types; the declared term
types match their atom assignments; and removal of the two precursor C5 planar impropers
has been reviewed. The exporter is a deterministic serializer, not a parameter fitter.

## Topology and NAMD release

Require a warning-free real psfgen build and a reactant/product PSF comparison proving:

- identical atom identities/count and conserved ordered-pair and system charge;
- exactly the two registry crosslinks and both retained intrabase C5-C6 bonds;
- expected product atom types/charges and all reviewed stereochemical impropers;
- regenerated angles/dihedrals with complete parameter coverage; and
- complete stable-base-key to transient segid/resid reverse mapping.

Then require a zero-step NAMD load, staged lesion-local and global minimization, and a
real explicit-solvent 2 fs ordinary-mass trajectory. Audit finite energies, crosslink and
backbone integrity, chirality, clashes/piercing, and all engine warnings. HMR/4 fs remains
disabled until a separate validation passes.

## Independent release review

The final reviewer must be independent of the parameter fit. Freeze all topology,
parameter, template, validation, NAMD, CHARMM36/CGenFF, and license hashes. Record exactly
which intrastrand/interstrand/extra-base contexts passed. Only then run the ordered
`attach-asset` and `review-gate` commands. Topology attachment must include the exact,
case-sensitive `--patch-name` from the candidate manifest; a catalog entry is
simulation-ready only when
all nine gates and every required runtime asset verify.
