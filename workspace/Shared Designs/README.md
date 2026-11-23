# Shared Designs

Shared reconstructions belong in `workspace/Shared Designs/`. This folder is
tracked directly in the main NADOC Git repository. A normal clone or pull of
NADOC includes the folder and all committed designs; no separate remote or
submodule initialization is needed.

Open **Library → This computer → Shared Designs**. The default reconstruction
layout is `Shared Designs/All Origami/Dnnn/RUN/Dnnn.nadoc`. Keep required part and
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
.venv/bin/python -m scripts.agent_structure_guard "workspace/Shared Designs/All Origami/Dnnn/RUN/Dnnn.nadoc"
```

Author parts through `scripts.agent_structure_guard.publish`. Verify assemblies'
recorded process and dependencies separately. Failed audits block publication;
transfer does not certify scientific validity or simulation readiness.

Keep simulation jobs, trajectories, credentials, and development evidence out of
this folder. Development inputs and reports belong under
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
