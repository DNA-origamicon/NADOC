# VR loading review — 2026-09-27

Integrated `origin/feature/standalone-viewer-presentations` at `49b37297` into
master as `7c235bb4`, preserving local edits, including VR shadow parity.
The incoming changes improve desktop instance construction, compact trajectory
updates, surface generation/remeshing, and CUDA startup. The desktop atom builder's
reported 1.40–1.58× construction improvement does not apply directly to the native
OpenGL viewer, which consumes its own exported scene.

## Measured change

`_snapshot` builds and serializes all four representations in both natural and
expanded poses before launch, regardless of the initial representation. Within
each pose, atomistic atoms and both copies of their bonds repeatedly calculate
nucleotide ownership and encode the same base/domain/strand selection tokens.

A cProfile sample with 6,000 synthetic atoms found 139,273 selection-token calls
and 31,494 nucleotide-owner calls. Selection-token encoding accounted for 0.609 s
of the 1.672 s instrumented export; these are overlapping cumulative profile
times, not additive or uninstrumented load timings.

The change adds two export-local LRU caches, each limited to 8,192 entries, and
reuses already validated atom base keys. Caches cannot survive into another
design or export. Output order, ownership, identities, numeric formatting,
geometry, and rendering are unchanged. The previous shadow-parity fix remains.

Reproduce the paired serialization benchmark (no workspace writes):

```sh
uv run python -m scripts.benchmark_vr_loading --baseline 0113bded --repeats 3
```

The fixture has 20 synthetic atoms per residue and consecutive bonds. Each sample
streams all four representations for one pose and checks the complete wire SHA-256
and ownership manifest against the original function loaded from Git. Timings
exclude atom construction, expanded-pose generation, gzip, native parsing,
GPU upload, OpenXR startup, and headset rendering. Full and Ball-and-Stick select
different headers but perform the same bundled export work.

Raw results and focused-test logs are retained under
`.development-artifacts/vr-loading/`. Initial timings overlapped the fast suite;
only `benchmark-idle.jsonl` is used for the final reported comparison.

Three alternating timed pairs after one warmup pair, median seconds:

| Atoms | Initial view | Before | After | Speedup |
|---|---|---:|---:|---:|
| 6,000 | Full | 0.617 | 0.322 | 1.92× |
| 6,000 | Ball-and-Stick | 0.629 | 0.325 | 1.94× |
| 30,000 | Full | 3.205 | 1.655 | 1.94× |
| 30,000 | Ball-and-Stick | 3.194 | 1.662 | 1.92× |

## Further opportunities

1. **Share immutable atomistic metadata and bonds.** Ball-and-Stick and Stick
   duplicate bond serialization and ownership. Natural and expanded poses also
   duplicate identity/owner tables. A versioned scene format could store these
   once, with pose-specific coordinates and representation membership. Preserve
   all exact atom/tool targets and current instant switching. This is the largest
   structural candidate from source inspection, not a measured speedup.
2. **Compact native transport and token interning.** The C++ reader uses formatted
   stream extraction and repeated string sets/maps for validation. Binary numeric
   blocks plus indexed identity/owner tables could cut parse cost and memory.
   Retain legacy text/gzip readers, validation, and error behavior; measure parser
   time and resident memory separately before choosing a format.
3. **Batch coordinate transforms and expanded offsets.** Current export rotates
   each atom through a separate small NumPy operation and deep-copies atom objects
   for Expanded. Packed coordinate arrays could reduce allocations and batch the
   work. Coordinate rounding, nonfinite filtering, crossover interpolation,
   extension ownership, and source immutability need exact parity checks. This
   was not the dominant hotspot in the measured serialization fixture.
4. **Stage first display.** Loading the initial representation before the rest
   could improve time to first visible model, particularly Full. This changes the
   current instant-switch contract until background loading finishes, so it needs
   explicit loading/error states and cancellation, not an invisible omission.

Do not optimize loading or frame rate by disabling the atomistic shadows just
requested. Measure dense-scene frame timing separately from CPU export latency.

## Verification limits

Focused VR routes, projection, and contract tests: **77 passed**.
The real `Examples/2hb_xover_atoms_test.nadoc` design (1,740 atoms) produced
byte-identical natural and expanded snapshots before/after. The bundled gzip
snapshot passed native `--validate`: 54,748 records, 55.4 ms parse/validation
time in one run. Its temporary directory was removed automatically. This is
functional loader evidence, not a paired parser performance result.

`just test-smart`: **FAST**, **9,257 passed, 91 skipped, 1 failed**. Failure:
`tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`
(exact scalar/array base-position comparison). Both the test and geometry source
are unchanged from pre-merge `0113bded`; this change touches export metadata only.
The failing test also reproduces in an isolated focused run. Ruff and
`git diff --check` pass for the changes.

Selector notice:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

No live browser state, user design, or simulation was modified for verification.
No headset timing or visual pass is claimed.
