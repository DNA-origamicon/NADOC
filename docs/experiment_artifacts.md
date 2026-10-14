# Generated experiment evidence

Keep analysis code, compact reports, provenance, and small regression fixtures readable in Git.
On this workstation, all new large outputs and temporary simulation/development
files belong on `/media/jojo/Archive/NADOC_archive/runtime/development-artifacts`,
via the repository's `.development-artifacts/` symlink. This includes native
scratch and large captures, not just final results. Verify the Archive mount and
resolved filesystem before writing; configure `TMPDIR`, engine scratch and output
paths explicitly. Never fall back to the system disk if Archive is unavailable.
The October 11 existing-data inventory requires user review before any relocation
or deletion; see [storage policy](../memory/feedback_development_artifact_cleanup.md).

Large generated per-pair/per-frame JSON summaries should be retained as deterministic gzip
artifacts, with an index containing SHA-256 of the **original uncompressed bytes**, original
and compressed sizes, and pair counts. This preserves exact evidence and makes code reviews
manageable. Compression reduces checkout size and future additions; it does not rewrite or
shrink existing Git history.

The exp59/exp60 summaries are indexed in `experiments/summary_artifacts.json`. Their existing
CSV and Markdown reports remain the human-readable summaries. Original trajectories and
NPZ series retain their existing local/archive locations and are not newly bundled here.
The gzip archives alone are evidence, not a complete environment for rerunning simulations.

- Verify every archived byte: `uv run python scripts/archive_experiment_summaries.py --check`.
- After regenerating either campaign: `uv run python scripts/archive_experiment_summaries.py --pack`.
  This refreshes the index and losslessly packs any legacy plain summaries. It verifies each
  compressed replacement before removing its plain counterpart; it is safe to rerun.
- Read a legacy logical path using `backend.core.json_artifacts.read_json_artifact(path)`.
  Both campaign readers and their cached-run checks accept plain or compressed results.
- Recover exact original bytes: `gzip -dc summary.json.gz > /tmp/summary.json`.

Both campaign writers now emit gzip summaries directly; raw summary paths are ignored to
avoid accidentally recommitting pretty-printed dumps. Other consumers of
`write_kimmdy_outputs` retain the plain-JSON default. If rerunning a campaign changes evidence,
refresh and review its index together with its compact report.

Use the archive destination above for new multi-gigabyte outputs. Keep portable
provenance and verified relocation indexes; do not replace evidence with dead URLs
or unverified local pointers. Preserve tracked reports and useful failed-run
evidence when proposing migration of older checkout-local artifacts.
