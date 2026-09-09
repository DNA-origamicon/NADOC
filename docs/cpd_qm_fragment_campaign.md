# TT-CPD local fragment QM campaign

## Decision

The routine TT-CPD parameterization target is no longer a separately optimized,
charged 63-atom d(TpT) model for every ordered isomer. The submitted Alpine
full-boundary job is intentionally unchanged and may finish as useful independent
validation. New local work follows the model-compound hierarchy used by additive
CHARMM development:

1. retain the complete, covalently connected TT-CPD core in a neutral 36-atom
   N1-methyl model;
2. retain one complete deoxyribose at a time in a neutral 49-atom endpoint-boundary
   model, with the other N1 methyl-capped and the open backbone oxygen hydroxyl-capped;
3. transfer unmodified sugar-phosphate chemistry from CHARMM36; and
4. validate the assembled patch in full d(TpT), short DNA, and NAMD rather than fitting
   the entire DNA environment quantum mechanically.

This partition and its release limits are machine-readable in
`backend/data/forcefield/photoproduct_qm_fragment_policy_v1.json`. It is based on the
[CGenFF model-compound protocol](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/),
the [CHARMM modified-ribonucleotide workflow](https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/),
the [CGenFF 5.0 four-membered-ring training/validation split](https://pmc.ncbi.nlm.nih.gov/articles/PMC11938330/),
the [N-methyl CPD electrostatic model of Masson et al.](https://doi.org/10.1021/ja076081h),
and CPD [QM/MM work that restricts the QM region to the reactive bases](https://doi.org/10.1021/jacs.6b06701).

## Prepared inputs

The prepared, non-executed campaign is stored at:

`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1`

Its `campaign_manifest.json` contains hashes, source evidence, resource estimates, and
the exact status of every case. Each new endpoint model has 49 atoms, charge zero, 449
6-31G(d) orbital basis functions, a complete ordered product graph, and a passed starting
chirality audit. Psi4 inputs request 12 GiB and six threads so one job can run locally
without consuming all workstation memory. No `output.dat` or run manifest was created
during preparation.

## Work breakdown and estimates

Estimates are elapsed time for sequential local execution. Geometry-optimization time
is sensitive to optimizer steps, so the first job in each size class is also a benchmark.

| Batch | Need | Prepared work | Estimated local wall time |
|---|---|---:|---:|
| A: missing core minima | Complete distinct ring minima required regardless of parameter sharing | cis-anti-II, trans-anti-I, trans-anti-II; existing 36-atom inputs | 3–9 h total |
| B: primary glycosidic boundaries | Cover both ordered C1'-N1/sugar interfaces in the syn and anti families | cis-syn endpoints 1/2 and cis-anti-I endpoints 1/2; four 49-atom inputs | 24–72 h total |
| C: held-out transfer checks | Test family sharing before more QM is authorized | cis-syn-II endpoint 2 and trans-anti-I endpoint 1; two 49-atom inputs | 12–36 h total |
| D: dependent frequencies/scans | Fit force response and selected acyclic glycosidic torsions | Generate only after the corresponding minima pass | 40–140 h total |
| E: full d(TpT) | Independent boundary validation, not routine per-isomer fitting | Leave current Alpine submission alone; do not start a duplicate locally | Alpine-dependent |

Batch D is deliberately not instantiated from the unoptimized starting structures.
Frequency and relaxed-torsion inputs must hash-link to passed optimized geometries; making
them now would create scientifically misleading targets.

## Recommended order

1. Run the three missing 36-atom core minima. Start with `tt-cpd-cis-anti-ii`; it is a
   low-memory, short benchmark and is required no matter how the boundary parameters are
   shared.
2. Run `syn-primary-endpoint-1` as the 49-atom local benchmark.
3. If its memory and timing match the estimate, finish the other three primary boundary
   jobs.
4. Fit the provisional syn and anti boundary blocks, then run the two held-out fragments.
5. Generate frequency and selected torsion targets only where the fit lacks identified
   response information.
6. Expand to another 63-atom full-boundary QM calculation only if a registered transfer
   metric fails. Otherwise use the Alpine result, if it finishes, as the independent
   full-boundary check.

The first three steps are sufficient to begin a chemically complete cis-syn parameter
candidate. NAMD production remains fail closed until charge, bonded, topology,
placement, and real-engine audits all pass.

## Execution interface

Listing the prepared fragment cases does not launch anything:

```bash
/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1/run_selected.sh \
  /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1 \
  --list
```

After a case is explicitly selected, its eventual execution command is:

```bash
/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1/run_selected.sh \
  /media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1 \
  --run CASE_ID
```

The runner has no default execution path, uses NADOC's provenance-recording QM runner,
refuses to overwrite prior results, and places Psi4 scratch data under the Archive-backed
campaign directory.
