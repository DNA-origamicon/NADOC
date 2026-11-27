# Experimental MagicDNA simple-bundle interchange

This is an experimental developer bridge. Straight-bundle checks below passed;
the curved native batch workflow remains incomplete and caused desktop
interference. See [current status](magicdna_headless.md).

The initial command-line bridge supports a honeycomb six-helix ring and a contiguous
3×6 (or 6×3) square bundle. It transfers directed scaffold/staple routing through
caDNAno v2 JSON and constructs NADOC parts with real, independently replayable
editor operations. It is not a general MagicDNA `.mat` importer or a 3D pose bridge.

## Local MagicDNA version

Use `/home/joshua/Applications/MagicDNA2`, extracted editable source from the
[authors' free-form release linked in their README](https://github.com/cmhuang2011/MagicDNA).
The existing GitHub clone already contains free-form/MagicDNA 2 code; its main GUI,
`InitialGUI`, `freeformcurve`, and `hyperbundle` match the package before local fixes.
The [2023 paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10371015/) identifies the
free-form upgrade as MagicDNA 2.0. The package's app manifest says **1.0.1**: this is installer metadata, not a reliable
MagicDNA generation identifier. The original Git checkout is retained separately.

The official `.mlappinstall` SHA-256 is
`3c9035225bd495d923d609c6788511855d19f3f7db411652ecbc6cca5fbf16fb`.
The free-form package disables two hard-coded blocks still active in GitHub's
`functions/FFCurve.m`; use the extracted package source for further work.

The local launcher `Applications/MagicDNA-local/launch-from-wsl.sh` now selects
`MagicDNA2`. MATLAB R2020a, Bioinformatics Toolbox, and Statistics and Machine
Learning Toolbox are activated and working. Source files remain editable for
breakpoints/debugging. The package omits `Previous Mechanism/Hinge.mat`, which its
`main.m` opens on startup; the matching existing GitHub example was copied there.

Apply the reproducible local source patches after extracting a fresh package:

```sh
python3 -m tools.magicdna.prepare_matlab /path/to/MagicDNA2
```

The patcher checks exact source anchors and preserves line endings. It adds optional
file arguments, a routing-only parser mode that avoids random sequence assignment,
and headless export colors. It also fixes a verified upstream bug in both scaffold
compilers: at a crossover, the predecessor bp was overwritten with the current bp
before the pointer was written, producing nonreciprocal caDNAno routing. No geometric
constants or molecular coordinate algorithms were changed.

## Native curved test designs

For unattended native construction, save/reopen and independent recipe replay of
curved 6HB and 3×6 designs, see [the free-form development loop](magicdna_headless.md).
This is separate from the bounded straight-bundle NADOC importer below.

## Commands

Run from the NADOC repository using `.venv/bin/python`:

```sh
# Export a new directory containing routing.json, source.nadoc, manifest.json.
.venv/bin/python -m tools.magicdna export source.nadoc new-package

# Validate before passing a routing file to the MATLAB helper.
.venv/bin/python -m tools.magicdna validate new-package/routing.json --lattice HONEYCOMB

# Import a standalone MagicDNA caDNAno file (explicit lattice required).
.venv/bin/python -m tools.magicdna import designHC.json imported.nadoc --lattice HONEYCOMB

# Reconstruct MagicDNA's returned JSON, retaining the original upstream process.
.venv/bin/python -m tools.magicdna reimport new-package returnedHC.json returned.nadoc

# Restore the exact original part, including its sequences, from an unchanged package.
.venv/bin/python -m tools.magicdna restore new-package restored.nadoc
```

Use `SQUARE` and the native `SQ.json` output for 3×6 square bundles. Importing a
package's `routing.json` as a standalone file is refused: use `restore` or `reimport`
to retain its upstream history. Reimport currently requires unchanged routing;
edits need a future recorded reconciliation path, rather than discarding history.
`restore` verifies the source hash and routing graph before returning the original.

In MATLAB, with the patched MagicDNA source and NADOC helper on the path:

```matlab
cd('path/to/MagicDNA2'); addpath(genpath(pwd));
addpath('path/to/NADOC/tools/magicdna/matlab');
[model, parsed, report] = nadoc_magicdna_bundle('path/to/new-package/routing.json', 'HONEYCOMB');
model.ExportJSON('returned', 'path/to/new-output-directory');
```

This constructs native `BundleCylinderHC`/`BundleCylinderSQ`, `jsonObject`, and
`hyperbundle` objects, then invokes native routing compilers and `ExportJSON`.
For the native source regression, call
`verify_nadoc_bundle(sourceFile, lattice, newOutputDirectory)`. It runs the same
native compiler/exporter and asserts exact scaffold, staple, insertion, and deletion
arrays against the input, ignoring only empty padding.

The exporter writes both HC and SQ files; use only the one matching the actual
lattice. This helper is an explicit API, not a new MagicDNA GUI menu or a complete
saved-project loader. Occupied bp indices must be ≥1 for the native MATLAB compiler.
It preserves source indices after satisfying the bundle constructor's origin padding.

## Scope and fidelity

- One linear scaffold; linear staples; canonical equal-bp crossovers; no forced
  ligation substitutions. Circular molecules, noncanonical junctions, arbitrary
  footprints, overhang/extension features, and posed/deformed bundles are refused.
- Single-base insertion/deletion encodings are accepted. More complex insertions
  are refused. Editing indels after assigning sequences can invalidate sequence
  lengths; export refuses that state until sequences are reassigned. The end-to-end MATLAB examples currently have no indels.
- caDNAno carries no arbitrary bundle pose or assigned sequences. Each editor uses
  its own native geometry: NADOC uses 0.334 nm rise and 2.25 nm lattice spacing,
  whereas this MagicDNA source uses 0.34 nm and 2.5 nm. Exact routing agreement does
  **not** mean atom-coordinate agreement.
- Original sequences, poses, and construction history remain authoritative in the
  source sidecar. A reconstructed raw import has unassigned sequences. No random
  DNA sequence is silently substituted.
- NADOC imports use `helix-add-at-cell`, `strand-add`, `crossover-place`, and
  `loop-skip-insert`, retain exact input bytes, and embed a known upstream document
  with its complete history. Publication goes through `agent_structure_guard`.
- This first bridge is CLI/MATLAB only; no frontend implementation was changed.

## Verified examples

Portable files are in `workspace/Shared Designs/MagicDNA/simple-bundles-v1/`.
`6hb/` and `3x6/` contain the original packages and native MagicDNA exports;
`6hb-returned.nadoc` and `3x6-returned.nadoc` are reconstructed native exports.
The source fixtures use **synthetic repeating test sequences**, not experimental
sequence designs. Returned files deliberately have unassigned sequences.

| Bundle | Scaffold / staples | Nucleotides | Replayed import commands |
|---|---:|---:|---:|
| Honeycomb 6HB | 1 / 14 | 1,134 | 121 |
| Square 3×6 | 1 / 41 | 4,032 | 388 |

Both were parsed into native MagicDNA objects and recompiled/exported in Windows
MATLAB R2020a. Independent comparisons matched every directed occupied site, edge,
and indel mark; native parser walks also matched. Saved/reopened NADOC imports
passed independent replay and bond review: zero forced ligations, zero missing
bonds, zero backbone bonds longer than the 1.2 nm review threshold. This is an
interchange check, not simulation or experimental certification.

Local detailed reports and MATLAB logs are retained under
`.development-artifacts/magicdna-converter/`; installation/version evidence is under
`.development-artifacts/magicdna-setup/`. MATLAB's legacy JavaFrame and WSL UNC
change-notification warnings remain, but the tested GUI and routing exports work.

Focused validation completed: 14 Python cases (including two indel cases rerun
after correcting their initially sequenced fixture), two isolated Chromium app
checks, native MATLAB exact-array regression for both lattices, and Ruff checks.
Both returned parts were visually inspected. Browser copies/project stores and
review screenshots were removed; shared-file hashes remained unchanged in the
final isolated check. No broad regression suite or scientific simulation was run.
