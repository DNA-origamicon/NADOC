# Literature workflow setup on another machine

Use a current NADOC checkout and run commands from its repository root. Linux,
macOS, and WSL use the same relative paths; no particular username, hostname, or
Archive mount is required. On native Windows, use the installed Python command
and environment paths instead of the shell examples below.

## What Git carries

Git carries the review documents, registries, acquisition manifests, source indexes,
and research scripts. Publisher PDFs, archives and article metadata under ignored
`experiments/origami_publication_catalog/assets/` are local evidence and are not
included in a clone. Saved download/validation statuses describe the originating
run; they do not prove files exist on the current machine. The original image
catalog and older full-text corpus also require their own local evidence.

You can inspect the registries and begin metadata screening without downloading
the corpus. Read [the kickoff prompt](RESEARCH_KICKOFF.md) for the research goal.
Goal-tool state is session-local; the checked-in ledgers/checkpoint carry progress
between machines. Refresh the checkpoint from actual files when resuming.

## Python and storage

Use Python 3.12 or the repository's supported newer interpreter. Acquisition,
restoration, integration and their focused tests use the standard library. PDF
indexing additionally requires PyMuPDF in your selected Python environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pymupdf
```

Reuse an existing `.venv` instead of recreating it. The application environment
may also be provisioned through the repository's normal setup. Installing PDF
indexing support is unnecessary for reading the saved indexes.

By default, restored assets go into a local ignored `assets/` directory. Allow at
least 3 GiB free for the current ACS corpus, more for future expansion. If using an
external disk, mount it first and configure `assets` as a symlink to your chosen
directory before restoration. Do not replace an existing directory/link without
inspecting its contents. A broken link fails explicitly. Other legacy catalog
scripts expect this conventional `assets` path; a custom `--assets` argument to
the restore command alone does not reconfigure those scripts.

## Verify or restore ACS evidence

The check is read-only and returns a nonzero exit status for missing evidence:

```bash
python3 experiments/origami_publication_catalog/expansion/restore_acs_assets.py
```

Restore missing documents and publisher metadata through their retained public
URLs. The command verifies file sizes and SHA-256, checkpoints each file atomically,
and leaves acquisition/review decisions unchanged. It fails on corrupt existing
files rather than overwriting them. An interrupted run resumes by checking the
files already present. Expect several minutes for the 1.756 GB corpus and paced
metadata requests; changed or unavailable publisher files remain explicit failures.

```bash
python3 experiments/origami_publication_catalog/expansion/restore_acs_assets.py --restore
python3 experiments/origami_publication_catalog/expansion/restore_acs_assets.py
python3 experiments/origami_publication_catalog/expansion/test_acs_retrieval.py
```

Alternatively, copy the existing asset tree from another machine, preserving its
relative layout, then run the check. This command restores only the recorded ACS
sources, not every historical source or image in the catalog. The regular ACS
discovery downloader does not restore files whose records already say downloaded;
use this restoration command for a fresh machine.

For PDF indexing after restoration:

```bash
.venv/bin/python experiments/origami_publication_catalog/expansion/index_acs_sources.py
```

Indexing rewrites the derived indexes. Integration and `validate_acs.py` also
regenerate catalog outputs; run them only after inspecting local changes. Avoid
running the historical `build_map.py` without its historical acquisition inputs.

## Access and session handoff

Public ACS supplement restoration uses no authentication. Journal full texts may
need institutional access; connect through the current machine's supported VPN or
library login privately. A VPN connection on another machine is not inherited.
Do not copy browser sessions or credentials into Git or the research ledger.

Before switching machines, save batch decisions and the checkpoint and synchronize
the intended Git changes using the repository's normal user-authorized process.
Avoid concurrent edits to the same ledgers; retain both decision histories when
resolving conflicts. The kickoff prompt itself does not authorize commits or pushes
in future sessions.
