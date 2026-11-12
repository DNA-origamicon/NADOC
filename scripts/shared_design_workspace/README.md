# Shared Designs

This is an independent Git repository inside NADOC's workspace. Open **Library →
This computer → Shared Designs** to browse it, or choose the folder when saving.
The outer NADOC repository still ignores `workspace/`; use Git from this folder
to version these files. Synchronization is explicit, not a background service.

Use the identical `Shared Designs` folder name under each machine's workspace.
The absolute NADOC installation paths can differ. Assemblies should reference
parts as `Shared Designs/parts/name.nadoc`, with every referenced part and other
input included in this repository. Keep separate candidates under distinct names.

Keep generated designs and required document dependencies here. Development
inputs, recipes and reports belong in the owning NADOC checkout under
`.development-artifacts/all-origami/`. Preserve full construction histories
and source hashes in the native documents themselves.

## Connect the first machine

From this folder, after choosing a private, empty Git remote:

```bash
git status
git remote add origin REPOSITORY_URL
git add README.md AGENTS.md .gitignore
git commit -m "workspace: initialize shared designs"
git push -u origin HEAD
```

The initializer does not perform these steps. Replace `REPOSITORY_URL` with the
actual remote; Git hosting or an SSH-accessible bare repository can be used.

## Connect the other machine

From that machine's NADOC checkout (use the configured workspace if customized):

```bash
git clone REPOSITORY_URL "workspace/Shared Designs"
```

Do not initialize a second unrelated repository there. Both machines need NADOC's
nested-hidden-directory listing fix so `.git` stays out of the Library.

## Exchange a generation batch

On the generator machine, audit each saved agent-authored part from the NADOC root:

```bash
.venv/bin/python -m scripts.agent_structure_guard "workspace/Shared Designs/parts/name.nadoc"
```

Check assembly histories/replay and every file dependency separately; the part
guard does not certify assemblies. Record the NADOC commit, generation parameters,
input hashes and validation verdicts in the native process and separate development report. From this repository,
review `git status` and `git diff`, stage the specific batch files, commit and push.

On the simulation machine, save/close affected documents, check `git status`, and
run `git pull --ff-only` only with a clean checkout. Stop on divergence or conflict;
do not automatically combine molecular JSON. Refresh the Library after pulling.
Load the native document, verify dependencies and provenance, then run the target
engine's preparation/readiness checks using a compatible NADOC revision before
requesting a production run. Record both repository commits with the job.

Simulation jobs stay in the host's ordinary workspace job folders or explicitly
configured local storage. Keep reports with development evidence; do not put trajectories,
live job state, credentials or large simulation packages into this repository.

Git delivers exact saved inputs; it does not guarantee that every generated design
is physically valid or supported by every simulation engine. Existing deferred
polymerization and long-extension limitations still apply.

## All Origami generation

From the NADOC checkout, use `python -m tools.design_archive.shared_pipeline --help`.
The standard destination is `Shared Designs/All Origami/Dnnn/RUN/Dnnn.nadoc`.
Only this standalone native file is shared. Hashed inputs, recipes and `run.json`
remain in `.development-artifacts/all-origami/runs/` in the NADOC checkout.
Blocked extraction runs create no Shared Designs entries. Reviewed command recipes produce parts only after complete saved/reopened
feature replay; required unsupported fits block publication. The workflow does not
commit or push. `simulation_ready` stays false until separate scientific preparation.
See `tools/design_archive/README.md` in the matching NADOC code checkout for the
recipe contract, supported extraction profiles and remaining reconstruction gaps.
