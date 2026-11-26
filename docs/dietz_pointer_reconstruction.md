# Dietz Pointer v1.12 reference reconstruction

The delivered `workspace/Shared Designs/Dietz_Pointer_v1_12_mrDNA.nadoc` reproduces the exact
`mrdna/resources/json/pointer_v1_12_from_dietz.json` reference in the local
mrDNA distribution. Its repository is
<https://gitlab.engr.illinois.edu/tbgl/tools/mrdna>, checkout
`6b9dfdcb73959029a9538564581c5a9e37edaea9`. The remote endpoint was unavailable
during this task; provenance identifies the local source explicitly.

The unmodified source is retained losslessly in
`tests/fixtures/cadnano_dietz_pointer.json.gz`, with a companion provenance JSON.
SHA-256: `b2be312ef90f945cd0f6b5f134946019e7b1b52a763175820af72029342139f0`.

## Scope and fidelity

- 82 square-lattice helices; 15,238 realized nucleotides.
- One scaffold and 161 staples. The [2012 paper](https://doi.org/10.1073/pnas.1215713109)
  describes 163 staples. This delivery matches the pinned reference file;
  it is not certified identical to the paper's experimental oligo set.
- Every occupied source site's predecessor/successor pointer, helix lattice
  address, loop/skip declaration and staple color matches. There are 15,240
  occupied source slots; one paired deletion removes two realized nucleotides.
- Sequences are absent from the caDNAno reference. The scaffold is now assigned
  M13mp18 at offset 0, verified against the 2017 published staple cores below.
  Staple sequences remain unassigned in the document. No relaxation,
  molecular-placement edits, terminal extensions or topology substitutions were
  added. Idealized geometry is not the experimental cryo-EM conformation.

## Recorded construction

The actual user-facing Import caDNAno operation records importer v3, the original
source bytes and digest, identity policy and name override from an empty part.
This is reproducible source import, not a reconstruction of the original authors'
historical mouse operations. The saved part embeds its reference. Publication
uses `scripts.agent_structure_guard.publish`; verification reexecutes the import
without using recovery snapshots and checks physical-reference state. The saved
file is reopened and independently compared with the reference again.

```bash
uv run python -m scripts.reconstruct_dietz_pointer OUTPUT.nadoc \
  --report .development-artifacts/pointer-reconstruction-20261123/new-report.json
uv run python -m scripts.agent_structure_guard OUTPUT.nadoc
```

Existing outputs are never silently overwritten.

## Published scaffold sequence assignment (November 23 follow-up)

[Praetorius et al., 2017, Supplementary Table 2](https://static-content.springer.com/esm/art%3A10.1038%2Fnature24650/MediaObjects/41586_2017_BFnature24650_MOESM5_ESM.xls)
contains a `pointer staples` sheet with 161 sequences. Its uppercase origami
cores are bounded by literal lowercase `ag` and `acgttga` flanks; the raw cells
and source digest are retained in `tests/fixtures/dietz_pointer_2017_staples.json`.
The workbook SHA-256 is
`5c17b7d299d7033fa813022767642e180111770e0ac583b68afa33bbf0753725`.

All 161 core sequences match the imported routes using NADOC's standard
M13mp18 sequence (7,249 nt) at offset 0, including 7,249 complementary staple
bases and 740 unpaired thymidine passivation bases. An exhaustive check of all
7,249 circular origins found 161 exact matches at offset 0 and zero complete
staple matches at every other origin. This independently identifies a published
oligo set matching the 161-staple reference, despite the 2012 paper's 163 count.
The 2012 supplementary download was inaccessible; no comparison to its table
is claimed.

`scripts/assign_dietz_pointer_sequence.py` uses the actual recorded Assign
Scaffold Sequence endpoint, preserves the Import feature and existing document
history, refreshes the active branch through normal revision persistence, and
publishes only through the structure guard with the prior file digest checked.
The scaffold sequence SHA-256 is
`b3c09122aae6ef739486936b4cf83679d349488c0891924de6cd7210c44cfc16`.
No staple routing, nick, deletion, geometry or sequence was changed. The T
passivation values are comparison evidence, not an implicit staple assignment.
Saved/reopened independent replay and the published-sequence comparison pass.
The assignment report is in `.development-artifacts/pointer-sequences-20261123/`.

To reproduce on an unassigned reconstruction:

```bash
NADOC_DISABLE_SESSION_CACHE=1 uv run python -m scripts.assign_dietz_pointer_sequence OUTPUT.nadoc \
  --report .development-artifacts/pointer-sequences-20261123/new-assignment-report.json
```

## Bond geometry and software limits

The complete report measures all 15,076 realized backbone bonds and 901
interhelix bonds. The importer classifies 38 interhelix bonds as forced ligations
(4.22%). Twenty-three interhelix edges exceed the existing 1.2 nm displayed
backbone envelope (2.55%); the longest is approximately 1.759 nm. Neither fraction
triggers the mandatory >20% review gate. These residuals remain visible and are
not a claim of atomistic or simulation readiness.

The normal UI proof-capture budget still refuses this large embedded source.
Standalone guarded publication and independent saved-file replay succeed;
the interactive proof badge must not be described as passing. Shared UI proof
budgets and molecular-geometry constants were not changed.

Validation: 74 distinct focused backend tests pass across the selected runs, including original-byte upload,
route limits, poisoned-snapshot independent replay, publication/reopen and a
negative topology-comparison case. The isolated browser flow imports original
bytes, saves a temporary part, opens the delivered part and renders 15,238
nucleotides with its Import feature present. View framing is checked separately
from these state assertions. Development reports live under
`.development-artifacts/pointer-reconstruction-20261123/`.

The initial browser screenshot was too close to assess the object. After a
view-only oblique camera adjustment and F fit-all at 1800×1000, the whole part
was visually inspected. Screenshots (410,781 bytes in the final output), temporary
workspaces and isolated bridge credentials were removed after inspection;
`visual-verification.json` retains the result. No production frontend behavior
was changed (`main.js` task delta: 0 lines).
