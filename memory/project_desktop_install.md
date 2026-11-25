---
name: NADOC Linux desktop installation
description: Electron/Python host, HC24 acceptance fixture and opening measurements
type: project
---

# Desktop installation — November 24, 2026

## Current status — November 25, 2026

User requested stopping desktop development and committing the completed work.
Further app development is pending. Continue development in the shared browser
codebase; the installed app remains a snapshot until an explicit rebuild/package/
installation checkpoint. Preserve user documents/settings and repeat desktop
acceptance on updates. No automatic updater. Caching/progressive large-assembly
loading is proposed, not implemented or authorized to continue now.

Milestones 1–3 retain Python/FastAPI + Three.js, package with Electron, and improve
first opening. Implementation/commands/limitations: `docs/desktop_install.md`.
Host, build/install tools and isolated acceptance harness: `desktop/`.
Native loopback capability, explicit backend ownership, production root serving,
workspace picker, native captures and developer tools are implemented.

User's benchmark: HC24 cross-section from `24hb_0xT.nadoc`, standard Seamed
Autoscaffold → Full Autostaple → Route for polymerization, straight open-ended
30-mer. Newly authored native histories and independently replayed dependencies
live at `workspace/Shared Designs/Desktop Benchmarks/HC24-30mer-20261124/`.
No simulation, assembly flattening or extension substitution.

Opening avoids the full assembly browser upload round trip and removes a fixed
1.5s success overlay. Initial elongated/end-on views use a diagonal fit; manual
Fit preserves orientation. Cancellation waits for active import/render to settle,
then discards its document. It does not preempt synchronous computation.

Local release: `/media/jojo/Archive/NADOC_archive/runtime/apps/NADOC-20261124`;
menu entry `~/.local/share/applications/nadoc.desktop`. Default workspace is
Documents/NADOC; choose existing workspace explicitly. Bundled production snapshot
includes pre-existing worktree edits. Linux non-simulation workflow only; external
sharing helper and simulation engine resources are not certified. No C++ rewrite.

Focused unit checks and installed-window open/orbit/Full/select/hide/undo/recolor/
save/reopen/cancel/shutdown are the acceptance scope, not a full-suite watermark.
Local evidence: `.development-artifacts/desktop-milestones/`. Native window capture
is necessary: Playwright page screenshots sometimes omit WebGL even when canvas
pixels exist. Initial camera framing was fixed after that visual review.

## Menu-launch correction (same day)

Editor-launched acceptance inherited `vscode (unconfined)` and missed Ubuntu's
userns restriction for GNOME menu launches. Exact NADOC executable profile
`/etc/apparmor.d/nadoc-desktop-c114baad2144` is now applied with administrator
authentication. `desktop/install.py` emits `nadoc.apparmor` and
`enable-sandbox.sh` for future installs. No sandbox-disable flags or global
sysctl changes. Verified registered `gtk-launch nadoc` under unconfined user
systemd (`ExitType=cgroup`), process transitioned to its NADOC profile and
welcome window visibly displayed. See ISSUE-263.

## Milestones 4–5 request and preliminary benchmark — November 24

User supplied `/home/jojo/Documents/NADOC/ttest.nass`, referencing `test.nadoc`:
30 copies of a recorded HC24 part, 315 bp per helix. Both files were byte-copied
into isolated profiles/workspaces and verified unchanged after testing. No source
or production renderer changes. The user subsequently authorized large-scene rendering and native acceleration
as the next milestones. See the completion entry below.

Preliminary one-run Full CG baseline: 90,322,560 triangles, median 30 fps;
existing opt-in fast spheres: 28,586,880 triangles, median 60.2 fps. Actual
orbit/selection/hide/undo/recolor/save/reopen succeeded in both test copies.
Camera after orbit only shows part of the long chain: this is not comprehensive
close-up visual parity or a universal FPS result. Opening baseline ~579ms;
candidate was CPU-profiled, so its opening time is not a paired performance claim.
Photo-mode real-sphere fallback remains unfinished in sphere-impostor project
notes; do not silently flip its production default. Added optional `--impostors`
and compact `--profile-js` diagnostics to `desktop/benchmark.cjs`.
Evidence `.development-artifacts/desktop-m45/summary.json`; temporary workspaces
cleaned, test backends stopped. `main.js` task delta: 0. Preliminary screening is superseded by the completion below.


## Large-scene and native acceleration completed

User clarified that these are useful new milestones (not the unavailable original
numbering). See `docs/desktop_large_scene.md` for scope, commands and limits.
Desktop enables only fast CG backbone spheres (`fast-backbone=1`); the ordinary
browser/atomistic flags remain opt-in. Photo mode replaces backbone quads with
real spheres and standard front-face materials, retaining transforms/colors;
exit restores exact original geometry/material objects. Part picking and
assembly edit/save/reopen/photo/cancel flows passed in the packaged/installed app.

A small C++ integer metadata kernel identifies domain owners/opposite occupancy;
all coordinate/placement authorities are unchanged. Bundled through ctypes with
an existing NumPy fallback. New `desktop/build_native.py` uses system tools and
avoids inherited Conda linker/compiler settings; the verified library has no
RPATH or external shared-library dependencies. Ready/log capabilities expose
whether it loaded. `NADOC_NATIVE_DOMAINS=0` disables it before launch.

`ttest` final three-run median Full fps: 30.2→59.9 wide, 29.9→59.9 close; triangles
90,322,560→28,586,880. One candidate run stayed near 31 fps (unexplained and
retained). No opening gain: ~549→561 ms. Warm compact preparation: 27.35→21.10 ms
(21 alternating samples), exact compact packet bytes. Installed confirmation
also measured ~60 fps in both views. Local evidence `.development-artifacts/desktop-m45/`.
Same installed executable/path preserves AppArmor/menu setup; resources updated
only with the app closed. Original `test.nadoc`/`ttest.nass` hashes unchanged.
35 backend, 141 frontend and four host checks passed; `main.js` delta 0.
