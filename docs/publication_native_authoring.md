# Publishing reconstructed native designs

D005 now has a saved native part at `workspace/Shared Designs/D005.nadoc`.
It was constructed from `twist-supp.pdf`, diagram page 19 and table page 37,
without consulting the archived caDNAno file during extraction or construction.
The compiler emits 2,681 ordinary editor commands: lattice cells, loop counts,
directed strand domains, native crossovers/nonlocal joins and sequences.
Independent replay uses their recorded inputs, never saved output snapshots.

The published file contains 60 helices, one scaffold, 217 staples and 15,983
nucleotides. A separate post-publication comparison confirms every source
scaffold/staple pointer, relative lattice cell and insertion count matches the
archived native reference. The 144-base insertion remains a scaffold loop.
No terminal extensions or relaxed geometry were substituted. The native idealized
lattice is not a prediction of the experimental twisted/relaxed conformation.

Reproduce into a new destination (existing designs are never overwritten):

```sh
uv run python -m scripts.reconstruct_publication_design \
  --pdf experiments/origami_publication_catalog/assets/sources/twist-supp.pdf \
  --diagram-page 19 --table-page 37 --name D005 \
  --output 'workspace/Shared Designs/D005.nadoc' \
  --evidence .development-artifacts/d005-native-construction
```

Publication goes through `scripts.agent_structure_guard.publish`, then the saved
file is reopened, replayed and compared with the extracted evidence. The portable
supplement, construction code hashes and audits are in `.provenance/D005/`.
The exact extraction implementation used for the first saved design is retained
there; subsequent compiler checks additionally reject unexplained unpaired
scaffold runs. Those checks leave D005's operation recipe unchanged.

The native loop-count operation and its history editor now accept 1–512 inserted
bases, -1 for a single deletion, and 0 to remove a mark. Existing single-base
operations replay unchanged. Preview work accounting charges the full insertion
count. Agent process audits remain bounded to 4,000 rows, including routing-group
wrappers; recipe construction is separately bounded to 3,800 operations. Every
row is still replayed and all existing publication checks remain mandatory.

D006–D009 are not saved native documents. D006 lacks a complete numbered lattice
inset; D007 has unexplained unpaired scaffold runs; D008 has unclassified routing;
D009 has repeated lattice labels, unmatched staple routes and an unverified
one-base discrepancy. The compiler refuses these cases. A table-row sequence
match is not permission to invent missing topology or placement.

The welcome screen lists saved `.nadoc`/`.nass` documents. README rows and transient
analysis results do not create library entries. Browser verification opened D003
and D005 through the actual welcome Library in an isolated workspace populated
with byte-identical copies of the published files; original files were not opened
for writing by the browser.
