# Large-scene rendering and compiled metadata processing

**Status (November 25, 2026):** completed performance checkpoint; further app
development is pending at the user’s request. See [development and update policy](desktop_install.md#development-status--november-25-2026).

November 24, 2026. The user supplied `~/Documents/NADOC/ttest.nass` and authorized
these as the next two desktop performance milestones. It references `test.nadoc`:
a standard recorded 24-helix honeycomb part with 315 bp per helix, repeated 30 times.
Benchmarks copy the assembly and dependencies into owned temporary workspaces;
source files are hashed before and after, never saved by the harness.

## Interactive rendering

The desktop host now enables **fast backbone spheres**. Existing shader-based
sphere rendering replaces 140-triangle beads with two-triangle camera-facing
quads. It retains bead centers, radii, instance transforms, colors and picking.
Slabs, 5′ cubes, connectors and atomic rendering keep their existing paths.
Browser use stays opt-in; the desktop launcher can use `--standard-spheres` for
the original rendering path. This is interactive GPU rendering, not molecular
simplification or a reduced nucleotide count.

Photo mode converts these backbone quads to ordinary sphere geometry at the
same radius, applies its normal materials and reinstalls the shared assembly
placement shader. Exiting restores the original interactive geometry/materials.
This conversion does not enable unrelated atomistic-impostor photo paths.
Shader sphere edges can differ from tessellated spheres in interactive views;
photo mode retains conventional geometry.

## Native metadata kernel

`native/desktop/domain_assignment.cpp` is a small compiled C++ integer kernel,
called through `backend/core/domain_assignment.py`. It finds the last matching
strand-domain owner and opposite-strand occupancy for each nucleotide row.
Python retains the object/string mapping and all existing coordinate, slab,
deformation and topology authorities. It changes no floating-point placement.

`desktop/build_native.py` compiles a dependency-free shared library using a clean
system toolchain environment. `desktop/build.py` bundles the library and source;
the manifest binds its bytes. `NADOC_CXX` explicitly selects another compiler.
Do not inherit a development environment's generic compiler/linker paths into a
release. The validated library has no external DT_NEEDED entries or RPATH.

Missing/disabled native code uses the existing NumPy path. Set
`NADOC_NATIVE_DOMAINS=0` before launch to disable it. Desktop readiness/logs expose
`native_domain_acceleration` so acceptance can require that compiled code actually
loaded. The native kernel is deliberately narrow: models requiring general
geometry processing retain their existing path.

## Verification and reproduction

The focused native tests compare overlapping domains, duplicate nucleotide rows,
empty inputs, opposite-strand occupancy and fallback behavior against independent
integer interval logic. Existing compact-geometry tests compare all values and
binary64 bits across straight, loop/skip, bent and other supported cases.
The `ttest` compact transport packet is identical with the compiled path on/off.

```sh
scripts/validation_guard.sh .venv/bin/python desktop/build_native.py \
  --output /absolute/scratch/domain.so
scripts/validation_guard.sh .venv/bin/python -m scripts.benchmark_desktop_native_domains \
  --part /absolute/test.nadoc --library /absolute/scratch/domain.so
```

The desktop acceptance runner adds `--matched-camera`, `--detail-view`,
`--detail-distance`, `--reference-view REPORT.json`, `--photo-check`, and
`--require-native`. The reference report supplies exact camera poses. Actual
orbit, Full display, selection, hide/undo, recoloring, save/reopen, and photo
entry/exit run in the window. Photo exit checks unchanged source matrices and
restored geometry/material identities. Source hashes and backend cleanup are
checked even on failure. Initial diagnostics and CPU profiling are separate from
final repeated timing runs.

Local evidence is under `.development-artifacts/desktop-m45/`. Opening is timed
separately from startup; OS file caches are not flushed. Frame samples cover only
the recorded viewport, camera and workstation GPU. No simulation is performed.
Neither a component speedup nor a triangle reduction implies the same improvement
in total application latency. Broad regression-suite debt remains separate.

## Results on this workstation

RTX 3080 Ti, 512×883 molecular viewport, three fresh-process runs per renderer.
The candidate received the baseline camera poses; resulting camera components
agree within 1.2e-16 (normalization rounding in the up vector).

| Measurement | Original installed app | Candidate |
| --- | ---: | ---: |
| Median Full-view frame rate, wide view | 30.2 fps | 59.9 fps |
| Median Full-view frame rate, close view | 29.9 fps | 59.9 fps |
| Submitted triangles | 90,322,560 | 28,586,880 |
| Median opening after app readiness | 548.8 ms | 560.5 ms |
| Warm compact-geometry preparation, 21 alternating samples | 27.35 ms | 21.10 ms |

Rendering submits 68.4% fewer triangles. The compiled metadata path reduces this
component's time by 22.9%; its compact packet is byte-identical. Opening is
essentially unchanged in this small sample. These figures are separate effects.

One of the three candidate runs had median 31.1/31.0 fps instead of ~60; it is
retained in `candidate-final.json`, and its cause is not established. Therefore
60 fps is not a guarantee. Selection timings after photo exit include shader
recompilation and are not comparable with the baseline's earlier selection step;
no selection-latency gain is claimed. Preliminary and failed harness attempts are
not substituted for the final measurements.

The installed confirmation checks loaded compiled code, actual editing and
save/reopen, photo restoration, cancellation and backend shutdown. Part-mode
confirmation additionally clicked a visible backbone bead and verified selection.
Focused checks: 35 backend tests, 141 frontend tests and four desktop host tests.
`main.js` delta for this work: 0 lines. No simulation or molecular geometry change was made.

The existing installation path and Electron executable are retained, so its
AppArmor profile and application-menu entry remain valid. Runtime resources were
replaced only while NADOC was closed; user profiles/workspaces were retained.

For a repeatable baseline with the new installed binary, launch with
`--standard-spheres` and `NADOC_NATIVE_DOMAINS=0`. This selects the retained
rendering and metadata paths. The normal user workspace and profile are never
used by the acceptance harness.
