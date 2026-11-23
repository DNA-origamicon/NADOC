# Imported and reconstructed design bond review

An import with **more than 20% forced-ligation bonds** requires review. Any
agent reconstruction with **more than 20% stretched backbone bonds** also
requires review. These are screening thresholds, not an assertion that a design
below them is physically valid. Exactly 20% does not trigger the numerical rule.
Incorrect overhang semantics, invalid routing and individual serious geometric
defects remain reasons to stop regardless of the percentage.

## What is measured

The read-only report counts unique realized covalent backbone edges from the
strand paths, including insertion/deletion routing. It does not invent circular
closure: the current Strand model has no circular-state flag, and a pending
terminal connection record does not establish an edge in the realized path. A
pending crossover annotation is not a bond. A forced-ligation record counts only
when it matches a realized edge. Ordinary and forced junctions share the same
denominator; replacing a crossover record cannot make the problem disappear.

Report both fractions, and trigger review if either exceeds 20%:

| Population | Purpose |
| --- | --- |
| All realized backbone edges | Implements the whole-design bond fraction. |
| Realized interhelix junctions | Prevents thousands of intrahelix edges from concealing a defective crossover network. |

The geometry screen measures **Full-view O5′ backbone endpoint separation**,
using the existing conservative **1.2 nm** native crossover envelope. Native HC
classes verified during the importer repair span approximately 0.749–1.085 nm.
This is a displayed-backbone metric, **not** a chemical O3′–P bond length or a
claim that all crossover classes have identical lengths. Count edges exceeding
1.2 nm; do not compare every class to the approximately 0.810 nm staple class.
Unmeasured or unsupported geometry is reported as incomplete and requires review,
not silently counted as satisfactory. The report states its coverage explicitly.

## Import and agent workflow

1. Preserve the original source, its digest, importer version and genuine
   construction history. Never repair routing by substituting forced ligations
   or author overhangs as terminal extensions.
2. caDNAno and scadnano application imports compute the report. A breach appears
   through `import_warnings` and marks the real recorded Import feature for
   review. `import_bond_review` contains the structured counts and examples.
   Legacy fallback imports retain their unverified provenance status. Import
   remains available for diagnosis; this warning is not acceptance for simulation.
3. Run the same report during reconstruction, after connection/placement changes,
   and before delivery. Do not wait until a completed design has accumulated
   hundreds of suspect junctions. Recompute after edits; an old import label is
   historical evidence rather than the current verdict.
4. When flagged, inspect representative junctions in the actual 3D view and
   retain numerical examples and visual evidence. Refer to helices by their
   visible labels in the exact design. Check source routing, native crossover
   sites, bp origin, lattice frame, phase/twist, helix extents and classification.
   Compare with a native control; a phase or axis defect can stretch correctly
   classified crossovers. Sequence matching and successful replay do not test it.
5. Correct the cause through recorded operations and repeat the report. If the
   unusual connections are intentional, document the investigation, interpretation
   and remaining limitations in an exact-design review receipt. Do not create a
   generic approval, automatically accept a flag, or relabel/delete connections
   just to lower the numerator. Review acknowledgment is not a geometry change
   authorization or a physical-validation certificate.
6. Publish through `scripts.agent_structure_guard.publish`. The guard checks bond
   review and independently checks complete process replay. A receipt cannot
   waive provenance, document ownership, source integrity or molecular-change
   authorization. Saved/reopened verification remains mandatory.

Reports and review evidence belong under `.development-artifacts/`; they are not
new structure features and cannot substitute for missing construction history.
Read-only diagnosis of a rejected legacy file does not authorize republishing it.

## Commands and documented review

Generate a report without changing or publishing the design:

```bash
uv run python -m scripts.agent_bond_review workspace/Design.nadoc \
  --output .development-artifacts/design-bond-report.json
```

Normal independent audit/publication refuses an unreviewed breach with
`DESIGN_BOND_REVIEW_REQUIRED`. After completing the investigation, audit with its
receipt using `python -m scripts.agent_structure_guard DESIGN.nadoc --bond-review
RECEIPT.json`, or pass `bond_review=receipt_path` to `publish`.

A receipt uses schema `nadoc-design-bond-review-v1`, the report's `design_sha256`
and `report_sha256`, a named `reviewer`, timezone-qualified ISO `reviewed_at`,
`decision: "reviewed-for-publication"`, and a substantive `rationale`. Its
`evidence` list contains at least one `visual` and one `bond-report` item, each
with `kind`, `path` and verified file `sha256`. Relative evidence paths resolve
beside the receipt. The bond-report evidence must match the current design and
report. An incomplete geometry report additionally requires explicit
`limitations`. The CLI never automatically creates an acceptance receipt.

Any design change invalidates the receipt. The returned
`bond_review.review_status` records acknowledgment separately from process
verification; a reviewed warning remains a warning, not a physical pass.

## Relation to the HC importer repair

Importer v3 uses the native axes, phases, exact lattice twist and occupied helix
extents. Versions 1 and 2 remain pinned for historical replay. The deposited Gür
source imports with 350 ordinary crossovers below 1.2 nm, including all 342 core
junctions. Sixteen nonstandard overhang-root forced ligations remain a separate
geometric problem even though their fraction is below the new trigger. This is
not yet a validated nanoparticle simulation seed.

Read-only checks of the retained review files demonstrate why the junction
denominator is necessary:

| Existing file | Forced junctions | Junctions above 1.2 nm | Review trigger |
| --- | ---: | ---: | --- |
| Rejected Gür reconstruction | 341/342 (99.7%) | 342/342 (100%) | Both |
| Historical direct import v2 | 16/366 (4.4%) | 309/366 (84.4%) | Geometry |
| Repaired direct import v3 | 16/366 (4.4%) | 16/366 (4.4%) | Neither percentage |
| Native `6hb_e_test` control | 0/234 | 0/234 | Neither percentage |

The rejected reconstruction's 342 long edges are only 2.4% of its 14,347 total
backbone edges. Checking that denominator alone would miss the failure. Local
per-edge evidence is retained under
`.development-artifacts/bond-review-workflow-20261123/`; portable regression tests
use the deposited source fixture rather than depending on user workspace files.

Eligible native straight HC caDNAno exports preserve original frame/extents and
sequences through bounded NADOC metadata; arbitrary posed geometry is outside
that guarantee. See [the importer reference](../memory/REFERENCE_CADNANO.md).
