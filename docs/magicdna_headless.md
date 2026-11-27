# Experimental native MagicDNA free-form development loop

**Paused at the user’s request: batch execution interfered with normal PC use.**
Do not treat the hidden-graphics workaround as proven desktop isolation. No more
local MATLAB runs are scheduled. Resume in an isolated desktop/session or machine.

Verified before stopping: curved 6HB native construction, scaffold/staple routing,
save/export, and fresh-process reopen with exact geometry/routing and preserved
tolerance (nine sections, one scaffold, 45 staples). Independent rebuild was
interrupted; curved 3×6 has not run. **The complete closed loop is not verified.**
Eight focused Python tests passed before the final loader/graphics changes; the
queued rerun was cancelled. Earlier straight-bundle validation is separate.

`tools.magicdna.freeform` drives the authors' MagicDNA 2 free-form source through
its existing Sketch, Sweep, Assembly, scaffold/staple routing, save, load, and
caDNAno export operations. It creates native test designs; it does **not** yet
translate a curved NADOC design or import the returned curve into NADOC.

## Run

Use the extracted free-form source described in [the interchange guide](magicdna_interchange.md).
The local installation is `/home/joshua/Applications/MagicDNA2`, with Windows
MATLAB R2020a. Free-form curves additionally require Curve Fitting Toolbox
(`cscvn`, `fnval`); its license was checked successfully. Bioinformatics and
Statistics and Machine Learning toolboxes remain installed as described there.

From the NADOC repository, choose a new output directory:

```sh
export MAGICDNA_MATLAB='/mnt/c/Program Files/MATLAB/R2020a/bin/matlab.exe'
just validate-safe .venv/bin/python -m tools.magicdna.freeform --experimental \
  --source /home/joshua/Applications/MagicDNA2 \
  --output .development-artifacts/magicdna-freeform/my-run
```

`--case curved_6hb` or `--case curved_3x6` narrows the run; default is both.
`--timeout 300` bounds each MATLAB process. The environment variable avoids the
`just` variadic command wrapper splitting an executable path containing spaces.
Direct invocation also accepts `--matlab PATH`. WSL needs `powershell.exe` and
`wslpath`; the PowerShell watchdog tracks and terminates only its MATLAB process
tree on timeout. The runner refuses existing output directories and checks free
storage. Heavy runs use the repository validation guard and run sequentially.

This is unattended MATLAB **with Java/Handle Graphics**, not a verified
`-nojvm`/`-nodisplay` deployment. The experimental batch graphics helper attempts to keep figures hidden
and disable keyboard callbacks even when upstream calls `figure(f)` or installs
new shortcuts. Native graphics objects and current-figure semantics still exist.
Only Windows MATLAB through WSL has been exercised; the non-WSL launcher branch
is not a portability certification.

## Construction and evidence

The committed recipes under `tools/magicdna/recipes/` specify an open spline
through `(0,0,0), (0,0,30), (8,0,60), (24,0,86)`, length-table entries of 90 bp,
seed 731, native slicing and ssDNA defaults, and 6 bp staple clearance. These are
native sketch coordinates and length scaling inputs, not a claim of unchanged
NADOC coordinates. MagicDNA controls its own spline, frame transport, section
slicing, bp rounding, connection selection, and routing.

The harness invokes native table-edit callbacks and the same Sweep/OK/routing
callbacks used by the GUI. Source patches supply explicit inputs at modal
boundaries; they do not replace spline, lattice, geometry, or routing algorithms.
It does not use the obsolete `VisualizeFFC_noGUI_wNormalVector` path.

For each case, the runner uses three fresh MATLAB processes:

1. Build and route from the recipe; save native `design.mat`; export routing.
2. Reopen with native `LoadT`; compare geometry, routing arrays, connection
   tolerance, and embedded construction log; re-export routing.
3. Rebuild independently from the recipe; compare exact section geometry,
   curve frames, ordered operations, and routing/indel identity.

Python separately checks every exported predecessor/successor for reciprocity,
walks all strands (retaining circularity), and compares graph signatures. The
matching-lattice export is authoritative: HC for honeycomb, SQ for square.
MagicDNA writes both formats, but the alternate-lattice file is not a validated
conversion of the design's physical lattice. Export array entries can include
additional routing representations beyond the physical section cylinders.

Each build contains `recipe.json`, ordered `process.json`, native `design.mat`
with embedded recipe/process, `freeform.mat`, `report.json`, and MATLAB logs.
The free-form sidecar retains sketch frames and slicing results because the
native Assembly save format does not retain the Sketch tab. Root manifests hash
the native source and harness; `verified.json` is written only after all checks.
`review.png` is disposable visual-review output, not a construction source.

No `.nadoc` parts are created by this workflow. A future bridge must preserve the
upstream recipe/process and author NADOC features through recorded editor
operations and the publication guard; these native outputs cannot be repackaged
as history-free NADOC imports. Native test designs remain development evidence,
not sequence-assigned or simulation/experimental validations.

## Source fixes and limits

`prepare_matlab.py` supplies noninteractive routing I/O and the previously verified
crossover-predecessor fix. Its color fallback now also handles an existing but
unpopulated caDNAno color table, as encountered after native free-form routing.

`prepare_freeform.py` adds explicit Sketch/open-spline input, native acceptance of
slicing and ssDNA dialogs, staple-clearance input, and a filename argument to
`LoadT`. It fixes ssDNA dialog code that used `gcf` instead of the owning dialog.
It also removes a legacy `loadobj` override that changed every saved bundle's
connection tolerance to 15: newly constructed bundles saved 40. Loading now
preserves the serialized value rather than changing connection-search settings.
Both patchers use exact source anchors, preserve line endings, fail before writing
if any anchor is unrecognized, and are idempotent.

The original package/checkout remains the reference; local fixes are not upstream
releases. Legacy JavaFrame deprecation and WSL UNC change-notification warnings
may appear. Curved NADOC↔MagicDNA conversion, arbitrary twists/cross-sections,
sequence assignment, oxDNA export/simulation, and physical bond validation are
outside this loop's tested contract.
