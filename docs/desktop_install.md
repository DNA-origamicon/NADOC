# NADOC desktop: Linux milestones 1–3

## Development status — November 25, 2026

**Further desktop app development is pending (paused at the user's request).**
The Linux installation, opening improvements, large-scene rendering and native
metadata acceleration are completed checkpoints; the existing installation remains
usable. Continue ordinary NADOC development in the shared browser codebase.

The installed app is a packaged snapshot and does not automatically track checkout
changes. Refresh it at an agreed checkpoint by rebuilding the frontend, packaging
the backend/native library, and installing the release with NADOC closed. Preserve
user workspaces/settings and verify menu launch, file opening, editing/save/reopen,
photo mode and shutdown. No automatic updater is implemented.

Persistent geometry caches, progressive first display and further large-assembly
loading/memory work are proposals only; implementation is deferred until desktop
work is explicitly resumed. See [measured results](desktop_large_scene.md).

The first desktop release retains Python/FastAPI and the existing Three.js UI,
hosted by Electron. It bundles Python 3.12 and the installed dependencies; the
installed UI does not require Node, npm, a browser tab, or a development server.
There is no C++ rewrite in this stage. Optimize measured hot paths before choosing
native kernels. Linux x64 is the currently exercised target.

## Running and debugging

Launch **NADOC** from the application menu. The initial workspace is
`~/Documents/NADOC`; use **NADOC → Choose workspace for next launch** to select an
existing library. Each release also provides `NADOC.sh --workspace ABSOLUTE_PATH`.
The application owns a loopback backend on an OS-selected port, protected by a
per-launch capability. Closing the last window stops that backend. Diagnostics
provides developer tools, logs and a native window capture. Development and
installed releases use the same UI and recorded authoring commands.

On this workstation the initial installation is
`/media/jojo/Archive/NADOC_archive/runtime/apps/NADOC-20261124`.
The application-menu entry is `~/.local/share/applications/nadoc.desktop`.
The Archive mount must be available. Workspace documents are separate from the
installation; uninstalling the application directory and that menu entry does
not delete them. The install script refuses to replace existing installations.

## Visible milestones

1. **Reproducible measurement:** a recorded HC24 part and straight open-ended
   30-mer, isolated acceptance runner, load phases, GPU/renderer evidence,
   screenshots, memory samples and shutdown checks.
2. **Local installation:** Electron host plus bundled Python and production UI,
   workspace selection, logs, developer tools, exports through save dialogs,
   separate document windows and explicit backend lifecycle.
3. **Opening improvements:** assembly paths open directly on the backend instead
   of transferring the complete file through the browser; remove the artificial
   1.5-second success overlay; initial elongated-scene framing avoids end-on
   views; cooperative cancellation discards the document after the active step
   settles. Normal manual Fit preserves orientation.

Cancellation does not preempt synchronous Python or mesh generation. This stage
is not a general renderer replacement or a claim that all processing is faster.

## Acceptance fixture and reproduction

The portable fixture lives under
`workspace/Shared Designs/Desktop Benchmarks/HC24-30mer-20261124/`.
It uses the honeycomb cross-section and initial 126-bp length from
`24hb_0xT.nadoc`. Native operations are Bundle → Seamed Autoscaffold → Full
Autostaple → Route for polymerization. The part has 24 helices, 7,056 nucleotides
and 24 periodic seams; the assembly has 30 instances and 29 joins (211,680
nucleotides before any derived materialization). The assembly keeps the upstream
part history and file dependency. No simulation or flattened part was created.

`scripts/build_desktop_reference.py` authors through normal commands and publishes
through the structure guard. Its `--audit-existing` option independently audits
the saved part and replays the assembly without overwriting either file.

Install JS dependencies with `npm ci --prefix desktop` and run Electron's installer
if required by npm's lifecycle-script policy. Build the production frontend using
the repository's guarded build workflow. Supply an unpacked standalone Python
3.12 runtime to:

```sh
scripts/validation_guard.sh .venv/bin/python desktop/build.py \
  --output /absolute/new-release-directory --python /absolute/standalone-python
```

The builder bundles this worktree, including any existing local modifications,
and records source hashes and Python dependency versions. It materializes editable
Python packages. Dangling upstream package symlinks are omitted; external simulation
executables/resources are not certified by this non-simulation release.

Run focused acceptance serially under the validation guard:

```sh
scripts/validation_guard.sh node desktop/benchmark.cjs \
  --packaged --executable /absolute/installation/NADOC \
  --workspace workspace \
  --fixture 'Shared Designs/Desktop Benchmarks/HC24-30mer-20261124/HC24-30mer.nass' \
  --iterations 3 --workflows --cancel-check --require-useful-view \
  --output .development-artifacts/desktop-milestones/acceptance.json
```

The harness uses owned `__e2e__` temporary workspaces/profiles, hashes source files,
exercises actual orbit, Full display, selection, hide/undo, recoloring, save/reopen,
and verifies backend exit. All temporary application state is removed in `finally`.
Use a short `TMPDIR` path for Chromium Unix sockets. `NADOC_TEST_SCRATCH_ROOT`
selects scratch storage; bulk build/output storage must have adequate free space.

## Measurement limits

Evidence is under `.development-artifacts/desktop-milestones/` locally. Measurements
use fresh app/profile/backend processes with the OS file cache left intact. Opening
is measured after application readiness, separately from startup. “Uncovered” means
a submitted frame with loading/welcome overlays absent, not physical input-to-photon
latency. Native-window and canvas screenshots are inspected separately: ordinary
browser screenshots can omit an otherwise rendered WebGL surface.

Memory samples sum Electron working sets and exclude the Python backend. One-second
frame samples are observations at the recorded camera and representation, not a
universal frame-rate guarantee. Timing validation disables application lifespan to avoid
recovering simulation jobs or remote connections. A separate `--normal-lifespan`
installed run passed open/edit/save/reopen and shutdown in an isolated workspace
with no jobs and remote autoconnect disabled. Normal job recovery, simulations,
VR, remote sharing and other platforms are outside this acceptance scope. External
share-helper endpoints are unavailable in the standalone host; the core local
editing workflow does not depend on them.

## Workstation results (November 24, 2026)

Same installed executable and Python runtime, three fresh-process samples per
frontend version, 30-mer fixture, hardware WebGL on RTX 3080 Ti:

| Measurement | Baseline frontend | Optimized frontend |
| --- | ---: | ---: |
| Open to uncovered frame, median | 1.791 s | 0.624 s |
| Observed opening range | 1.771–1.800 s | 0.514–0.625 s |
| Initial view | End-on dot | Visible diagonal chain |

Median opening latency fell approximately **65%** (2.9×). Much of the gain comes
from removing the 1.5s success delay; this is not evidence of equivalent geometry
computation acceleration. A separate installed workflow run opened in 0.500 s;
the part opened in 0.657 s. App startup is measured separately and remains several
seconds (5.2 s in that installed workflow run). Freshly copied bundle runs ranged
5.6–12.3 s startup, so no cold-start improvement is claimed.

The Full representation check rendered 42,422,400 triangles at roughly 60 fps in
a one-second sample on this workstation. Baseline also achieved roughly 60 fps;
no frame-rate improvement is claimed. Electron peak working sets were around
1.1 GiB, excluding Python. The installed acceptance exercised both cancellation
paths with successful imports settling before discard. Earlier packaged-run
cancellation checks intercepted a 403 response and are not the cancellation
acceptance evidence; `installed-workflows.json` and `installed-part.json` contain
the corrected successful-response checks.

Focused checks: 88 frontend tests, 8 desktop/API tests, 5 assembly audit tests and
3 Node host tests passed, plus production build and installed interactive flows.
Saved/reopened fixture replay: `reference-final-audit.json`. Timing summary:
`results-summary.json`; complete traces and native window captures are retained
alongside it. These focused passes do not clear broad regression debt.

The workstation installation explicitly binds its trusted Shared Designs directory
to the existing repository folder. For other installations, pass
`install.py --destination ABSOLUTE_PATH --shared-designs ABSOLUTE_SHARED_FOLDER`
to support an external workspace linked to that exact folder. Arbitrary external
symlinks remain rejected. No documents are copied or rewritten by this binding.

Repository-wide hygiene checks still report pre-existing issues outside this task:
`just lint` finds an unused `Path` import in `tests/test_workspace_location.py`;
`just lint-memory` reports an unindexed `project_oxdna_occupancy_clouds.md` plus
existing size warnings. Task-owned Python lint and whitespace checks pass.
`main.js` task delta is +3 lines of imports/thin wiring; behavior is in modules.

## Ubuntu Applications-menu sandbox setup

The initial acceptance runs inherited VS Code's AppArmor profile. On Ubuntu
with restricted unprivileged user namespaces, that can pass while a launch from
GNOME fails before any application log exists. The journal reports an invalid
SUID sandbox helper, and kernel logs show a denied user namespace capability.

The installer now prepares `nadoc.apparmor` and `enable-sandbox.sh` in the installed
release. The rule names only that installation's exact NADOC executable and grants
`userns` using Ubuntu's unconfined application-profile pattern. Apply it with
administrator authentication (`sudo /absolute/installation/enable-sandbox.sh` or
`pkexec /absolute/installation/enable-sandbox.sh`). No global sysctl change or
`--no-sandbox` flag is used. A different install path requires its own rule.

On this workstation the applied rule is
`/etc/apparmor.d/nadoc-desktop-c114baad2144`. Validate future desktop releases from
the user desktop launch context, not just the editor's terminal. A user-systemd
service starts unconfined; `gtk-launch nadoc` with service `ExitType=cgroup` tests
the registered menu entry without killing its child as the launcher exits.

## Next performance milestones

The installed resources now include fast interactive backbone spheres with a
photo-mode real-sphere fallback, and a bundled C++ integer metadata kernel.
See [large-scene and native results](desktop_large_scene.md). Building this stage
requires a C++17 compiler; running the installed application does not.
