# Shared Designs

Open **Library → This computer → Shared Designs**. All saved designs are in this
folder directly; there are no per-design or per-run folders to browse. A normal
clone/pull of NADOC includes the committed designs and portable dependencies.

| Design | Saved document / status |
| --- | --- |
| D003 — corner motif | [D003.nadoc](D003.nadoc); current bond review and 1,692-command replay verified; long-junction limitations retained |
| Dietz Pointer v1.12 — mrDNA reference | [Dietz_Pointer_v1_12_mrDNA.nadoc](Dietz_Pointer_v1_12_mrDNA.nadoc); reference import and scaffold assignment; not a publication-image reconstruction |
| HC24 — periodic part | [HC24-polymerization.nadoc](HC24-polymerization.nadoc); upstream part for the 30-mer |
| HC24 — 30-mer assembly | [HC24-30mer.nass](HC24-30mer.nass); 30 instances, 29 joins |
| Spoked wheel — reinforced honeycomb | [Wheel reinforced.nadoc](Wheel%20reinforced.nadoc). Four six-helix spokes connect the shaft to a closed 40 nm rim. All 21 features replay. oxDNA2 completed 300,000 unrestrained steps at 296 K and 0.5 M salt with 71.7% of intended base pairs retained. [Bond review](.provenance/Spoked%20Wheel/receipt.json) |
| D005 — twisted bundle | [D005.nadoc](D005.nadoc); PDF-derived native construction, 2,681 replayed commands, 217/217 staples match |
| D006 — straight 3×6 bundle | [D006.nadoc](D006.nadoc); complete source topology, 209/209 staples, two independently placed loop tracks, 1,434 replayed commands; 18 polymerization seams and four nonlocal loop joins |
| D007 — monolith | [D007.nadoc](D007.nadoc); 60 helices, 144/144 published staples, 1,680 bare terminal scaffold bases preserved; 1,298 replayed commands |
| D008 — square nut | [D008.nadoc](D008.nadoc); 148 table staples plus one drawn 38-base staple with derived sequence; 1,186 replayed commands |
| D009 — railed bridge (partial) | [D009.nadoc](D009.nadoc); 194/197 table staples; 1,592 replayed commands; [completion report](D009.reconstruction.json) |
| D012 — genie bottle, pEGFP variant | [D012.nadoc](D012.nadoc); 54 helices, 121/121 published staple routes, one 71-base scaffold loop and 1,197 replayed commands; [completion report](D012.reconstruction.json) |

D005 was authored from the published figure/table using native editor operations,
without a caDNAno reference as a construction input. Its original supplement,
construction implementation hashes and publication/reopen audits are retained in
`.provenance/D005/`. This is the native idealized lattice model; experimental
twist/relaxation and simulation readiness are not certified.

Publication-analysis details and limitations: [routing extraction](../../../docs/publication_routing_extraction.md).
D009 is a partial native document visible on the welcome screen. Its report lists
the three omitted staples and remaining interpretation/geometry limitations. Development artifacts remain local.

Store future native designs directly here with unique, descriptive filenames.
Required review evidence lives in `.provenance/`; historical read-only source
paths resolve through `.relocations.json`, which binds their original SHA-256 and complete saved content except the two
ordinary workspace identity path/timestamp fields.
The consolidation preserved native histories and molecular content. NADOC’s
ordinary welcome-screen identity migration subsequently updated relocation paths
and timestamps; those two bookkeeping fields are explicitly allowed by the lookup.
Relocation aliases are for loading dependencies, not save destinations. Editing molecular content, construction history or other metadata
invalidates the historical alias;
record a new source selection rather than silently repointing old history.

## Save and synchronize

Save and close affected designs before synchronizing. From the NADOC repository
root, review `git status` and stage the specific reviewed files, then commit and
push. On other computers, use `git pull --ff-only` with a clean checkout and
refresh the Library. Saving a design alone does not publish it to Git.
Do not automatically merge conflicting molecular JSON or discard local edits.

Before committing agent-authored parts, run the required independent audit:

```bash
.venv/bin/python -m scripts.agent_structure_guard "workspace/Shared Designs/DESIGN.nadoc"
```

For D003's human-reviewed corner motif, repeat the audit from the NADOC root:

```bash
.venv/bin/python -m scripts.agent_structure_guard "workspace/Shared Designs/D003.nadoc" --bond-review "workspace/Shared Designs/.provenance/D003/receipt-20261125.json"
```

D003's read-only review was updated on 2026-11-25 and its saved process independently
replayed (1,692 commands). Molecular content and feature history are unchanged; normal workspace identity
path/timestamp updates are included in the current review binding. Current Full geometry
measures all 14,070 backbone segments, including 266 previously unmeasured insert
segments; 151 of those exceed the 1.2 nm screen, bringing the interhelix total to
572/687. The current receipt acknowledges those limitations for sharing and
inspection, not simulation readiness or a molecular repair. The original human
approval and receipt remain intact; the new agent review does not claim renewed
human approval. The complete seam census and current application views are in
`.provenance/D003/`, with dated filenames.

Its exact historical title exception is documented in
`scripts/agent_metadata_exceptions.py`. A changed design requires a fresh audit
and review; the receipt is bound to the saved design and report.

Author parts through `scripts.agent_structure_guard.publish`. Verify assemblies'
recorded process and dependencies separately. Failed audits block publication;
transfer does not certify scientific validity or simulation readiness.

Keep compact publication review receipts and their referenced evidence in `.provenance/` with
relative receipt-to-evidence links preserved so another computer can repeat its audit. Keep simulation
jobs, trajectories, credentials, and other development evidence out of this folder. Development inputs and reports belong under
`.development-artifacts/all-origami/`. Other workspace folders remain local.

## Existing installations

The old setup script created a nested Git repository without connecting a remote.
If `workspace/Shared Designs/.git` exists, inspect its status, history and remotes
and preserve that metadata outside the workspace before adopting the main-repo
layout. Do not delete an existing repository or overwrite local designs.
If a pull reports untracked files would be overwritten, back up those exact files
outside the workspace, compare them with the incoming versions, and reconcile
before retrying. Do not force the pull.

Git checks out this folder beneath the NADOC checkout. If `NADOC_WORKSPACE` points
elsewhere, explicitly arrange for that workspace's `Shared Designs` to use this
tracked folder (for example, a directory symlink where supported); changing the
workspace setting does not move Git's checkout.

### Archive-backed runtime workspace

Keep `workspace/` a real directory so Git can track Shared Designs. An ignored
`.nadoc-workspace` directory symlink at the NADOC checkout root can select an
existing runtime workspace on another drive. `NADOC_WORKSPACE`, when set, takes
precedence. An unavailable configured drive fails explicitly instead of creating
an empty replacement workspace.

Link that runtime workspace's `Shared Designs` to this checkout's
`workspace/Shared Designs`. NADOC lists and opens this specific trusted link,
while retaining workspace-relative document references. Arbitrary external links
and links escaping the shared folder are not permitted. Existing local designs
and jobs stay in the runtime workspace; only shared designs live in the checkout.
Do not overwrite an existing folder when creating either link. Preserve old
nested Git metadata outside the workspace before adopting this layout.

D006 preserves all 7,704 scaffold sites and 7,658 staple sites, with zero missing,
extra or incorrect reference pointers after mapping the two native loop tracks
back to source row 19. Native visible helix 18 is the loop from helix 0; native
helix 19 is the loop from helix 1. All 46 unpaired bases remain native scaffold
domains; no terminal extensions, inferred oligos or imported root were substituted.

This certifies source topology and recorded construction, not simulation geometry.
The source includes 18 same-helix end-to-end staple connections (~140 nm in the
straight monomer frame) and four auxiliary loop joins. The 18 end-to-end joins are now
explicitly marked as periodic polymerization seams, as confirmed by the user.
The four loop joins remain nonlocal. No axial fitting or relaxation was performed.
Staple construction uses 18 continuous body pens and two auxiliary-track pens,
then native endpoint nicks and crossovers; polymerization staples are drawn separately.
Portable source, code snapshots, replay and reference audits: `.provenance/D006/`.

D007 preserves the full 7,560-base scaffold and only the 144 published staples
(5,880 staple bases). The 1,680 terminal scaffold bases remain unpaired, 28 per
helix; no additional staples from the archived end-stapled variant are added.
All 13,295 backbone edges were measured with zero forced ligations and zero
Full-view O5 spans above 1.2 nm. This is an idealized native lattice model, not
a relaxed prediction of the bare ends. Source and replay audits: `.provenance/D007/`.

D009 is now available as **D009.nadoc (partial)** with 194/197 table staples. Read
[D009.reconstruction.json](D009.reconstruction.json) and
[its provenance](.provenance/D009/README.md) for the three omitted routes,
scaffold-length hypothesis, sequence conflicts and unrelaxed geometry limits.
