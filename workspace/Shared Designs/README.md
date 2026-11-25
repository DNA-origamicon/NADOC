# Shared Designs

Open **Library → This computer → Shared Designs**. All saved designs are in this
folder directly; there are no per-design or per-run folders to browse. A normal
clone/pull of NADOC includes the committed designs and portable dependencies.

| Design | Saved document / status |
| --- | --- |
| D003 — corner motif | [D003.nadoc](D003.nadoc); existing design retained unchanged; historical human review needs renewal under current geometry code |
| Dietz Pointer v1.12 — mrDNA reference | [Dietz_Pointer_v1_12_mrDNA.nadoc](Dietz_Pointer_v1_12_mrDNA.nadoc); reference import and scaffold assignment; not a publication-image reconstruction |
| HC24 — periodic part | [HC24-polymerization.nadoc](HC24-polymerization.nadoc); upstream part for the 30-mer |
| HC24 — 30-mer assembly | [HC24-30mer.nass](HC24-30mer.nass); 30 instances, 29 joins |
| D005 — twisted bundle | Analysis only; 217/217 staples match; no saved native model |
| D006 — twisted bundle | Analysis only; 209/209 staples match; lattice positions remain incomplete |
| D007 — monolith | Analysis only; 144/144 staples match; native routing completion remains |
| D008 — square nut | Analysis only; 148/148 staples match; native routing completion remains |
| D009 — railed bridge | Analysis only; loop-supported candidate with a one-base scaffold discrepancy and penalized confidence; unresolved, no saved native model |

Publication-analysis details and limitations: [routing extraction](../../../docs/publication_routing_extraction.md).
The reconstruction UI retains analysis results in its session; these rows do not
represent published molecular documents. Development reports remain local.

Store future native designs directly here with unique, descriptive filenames.
Required review evidence lives in `.provenance/`; historical read-only source
paths resolve through `.relocations.json`, which binds their original SHA-256.
The consolidation did not rewrite any native document, identity or feature log.
Relocation aliases are for loading dependencies, not save destinations. Editing
a relocated source changes its digest and invalidates the historical alias;
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
.venv/bin/python -m scripts.agent_structure_guard "workspace/Shared Designs/D003.nadoc" --bond-review "workspace/Shared Designs/.provenance/D003/receipt.json"
```

D003 is retained as an existing shared artifact, not recertified by this cleanup.
Its construction replay passed before upstream integration. With integrated
geometry code, the saved receipt fails `DESIGN_BOND_REVIEW_REQUIRED` because the
report changed: 266 previously unmeasured bonds are now measured, and long
interhelix segments increase from 421/687 to 572/687. The design digest is
unchanged. Keep the historical receipt/evidence intact; a new review is required
before further publication or scientific acceptance. Do not rewrite the receipt
to manufacture a pass.

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
