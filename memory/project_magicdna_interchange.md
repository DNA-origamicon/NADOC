---
type: project
status: active
authority: supporting
---
# MagicDNA interchange

Current guide: `docs/magicdna_interchange.md`. CLI and MATLAB helper live in
`tools/magicdna/`; tests in `tests/test_magicdna_simple_bundle.py` and
`frontend/e2e/magicdna_simple_bundle.spec.js`.

Local source: `/home/joshua/Applications/MagicDNA2`, extracted authors' free-form
package (manifest 1.0.1 does not mean MagicDNA 1). Windows MATLAB R2020a activated.
Launcher selects this source. Preserve original Git checkout. Exact-anchor patcher
adds noninteractive routing I/O, suppresses random sequence inference, and fixes
upstream crossover predecessor index corruption. Default Hinge.mat copied from
original checkout because package omitted it. See guide before reinstallation.

Working scope: honeycomb 6HB ring / square 3×6, one linear scaffold, canonical
crossovers. Actual native MATLAB round trips conserve directed graphs. No arbitrary
3D pose or `.mat` project bridge. Sequence/history sidecar mandatory for NADOC
origin; edited returned graphs need future recorded reconciliation. No forced
ligation substitution or captured-root history.

Portable audited examples: `workspace/Shared Designs/MagicDNA/simple-bundles-v1/`.
Development reports/logs: `.development-artifacts/magicdna-converter/` and
`.development-artifacts/magicdna-setup/`. No simulations were run. Returned examples
have unassigned sequences; source examples use synthetic repeating test sequences.

## Experimental checkpoint — November 26, 2026

User stopped native free-form testing because it interfered with normal PC use
and requested commit/push as experimental. Do not resume MATLAB runs implicitly.
Curved 6HB: native nine-section build, one scaffold/45 staples, export and fresh
reopen verified (geometry/routing/process and Tol=40 preserved). Full independent
replay interrupted; curved 3×6 recipe exists but has not been run. Closed loop is
not verified. Eight Python tests passed before final loader/graphics changes;
queued rerun cancelled. Hidden-figure/key-handler mitigation is not proven desktop
isolation. Use a separate graphical session/machine for future tests.

See `docs/magicdna_headless.md`, `tools/magicdna/freeform.py` (requires explicit
`--experimental`), and `.development-artifacts/magicdna-freeform/loop03/`. Native
source modifications are reproducible via the two committed patchers; external
MATLAB installation and local development outputs are not repository deliverables.
