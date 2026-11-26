# Shared Designs

Shared reconstructions belong in `workspace/Shared Designs/`. This folder is
tracked directly in the main NADOC Git repository. A normal clone or pull of
NADOC includes the folder and all committed designs; no separate remote or
submodule initialization is needed.

Open **Library → This computer → Shared Designs**. The default reconstruction
layout is `Shared Designs/DESIGN.nadoc`. Keep required part and
assembly dependencies in this folder, with workspace-relative references starting
`Shared Designs/`. Keep complete native feature histories and source hashes.

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

Its exact historical title exception is documented in
`scripts/agent_metadata_exceptions.py`. A changed design requires a fresh audit
and review; the receipt is bound to the saved design and report.

Author parts through `scripts.agent_structure_guard.publish`. Verify assemblies'
recorded process and dependencies separately. Failed audits block publication;
transfer does not certify scientific validity or simulation readiness.

Keep compact publication review receipts and their referenced evidence beside
the reviewed design so another computer can repeat its audit. Keep simulation
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
