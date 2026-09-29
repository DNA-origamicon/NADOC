# Watch the VR authoring workflows

From the NADOC repository on the configured Linux/Vive workstation:

```bash
uv run python -m tools.vr_workflows.demo
```

Keep SteamVR running and the headset tracked. The command uses the current built
native viewer and the owned idle-session record in
`.development-artifacts/vr-human-motion-live/launch.json`. It refuses to replace
an active browser-managed VR session. No VSCode, SteamVR, or display restart is
performed.

The visible browser creates a desktop 6HB, enters VR, paints/extrudes from the
default plane, extends an exact blunt end, and places a freeform extrusion. It
then checks Undo/redo, edits a cell in cadnano, saves, reloads, and shows desktop
3D geometry. A second run starts with an empty part and creates its first
extrusion directly in VR. The native headset mirror is brought forward during
VR actions; desktop/cadnano review pages come forward afterward.

Both runs use the synthetic `steady_fast` controller profile. Six-second review
pauses sit outside measured reaches. To change those pauses (0–30 seconds):

```bash
NADOC_VR_DEMO_HOLD=10 uv run python -m tools.vr_workflows.demo
```

Allow roughly 6–8 minutes. The command prints its unique evidence/log directory
under `.development-artifacts/vr-workflows/demo-*`. It retains failures and uses
one Playwright worker. Avoid manipulating the demo windows/controllers while it
runs. At completion it restores the owned idle viewer; it does not leave an
input loop running.

**Each run deletes old `.nadoc` files in `workspace/VR Testing`, including edited
or renamed files.** Move anything you want to keep elsewhere first. Successful
runs publish `desktop-then-vr.nadoc` and `vr-first.nadoc` there. These are editable
review outputs, never test fixtures or validation inputs. Other workspace folders
are not reset.

This is a visible demonstration with independent geometry, exact-target,
desktop-delivery, and round-trip checks. It is not the final 90% acceptance
campaign or proof of physical headset comfort. See
[the workflow development record](vr_authoring_workflows.md) for tested profiles,
retained failures, and remaining work.

Verified checkpoint (2026-09-23): both headed workflows passed in
`.development-artifacts/vr-workflows/demo-kzp60tl9/`. Final focused tooling tests:
69passed; native tests:36passed. The90%acceptance campaign remains unfinished.

## View Volumes demo and ScryWrite validation

Open **Debug → VR Tours & Tests → View Volumes** and choose **View volumes demo**
or **View volumes validation**. Both launch an isolated demo part and leave the
open document unchanged. Close any existing native viewer first.

Terminal equivalents:

```bash
just vr-view-volumes-demo
just vr-view-volumes-test
```

The demo uses `steady_fast` and pauses at visible milestones: create square/hex
volumes from the Visualization card, hide/show outlines, disable/enable and delete,
then highlight/grab a centroid, move/rotate, resize a side and an end face, and
move the scene with Grip while holding the centroid. It checks persistence too.
The final volume remains visible until **Stop tour** or Ctrl+C. To run a bounded
demo with shorter review pauses:

```bash
just vr-view-volumes-demo --hold 0.5 --exit
```

Validation uses the same ScryWrite inputs and assertions without review pauses,
runs both shapes across all four motion profiles, and exits automatically. The
menu checks use real trackpad/trigger input; they do not call action handlers.
Highlight assertions require expected pixels in both submitted eyes and include
a cold negative case. Geometry checks compare observed controller motion and
saved document coordinates, including independent side/radius and end-face resize.

Each run prints an evidence directory under `.development-artifacts/vr-view-volumes`
(or `.development-artifacts/vr-debug-tours` when launched from Debug), containing
`result.json`, motion trials, menu and highlight captures, and saved `.nadoc`
fixtures. Automated evidence tests reject blank, wrong-color, offscreen and
missing-eye captures. These are simulated controller checks in the physical VR
runtime, not a human comfort assessment.

## Fresh 6HB extrusion and view-volume tour

Debug → VR Tours & Tests → Tools · Authoring → **Extrude a 6HB and inspect a volume**
starts a new part in a temporary workspace. It paints the canonical six-helix
honeycomb ring through Tools → Extrude, confirms 42 bp, and uses a view volume to
show a different representation of a subsection. It never imports or replaces a
fixture or workspace review part. Evidence, including the newly authored .nadoc,
is retained under `.development-artifacts/vr-extrude/`.

```sh
uv run python -m tools.vr_workflows.extrude_tour
uv run python -m tools.vr_workflows.extrude_tour --validate
```

Demo uses steady_fast and pauses at review stages. Validation runs all four motion
presets. Both own their browser, temporary backend/workspace and native viewer.
The tour refuses to start while another native viewer is active.

The fresh-part Extrude tour also exercises lattice-window controls: two interior
grips zoom the painting lattice; border grips move/resize its window; the attached
thumb wheel sets extrusion length. Validation sweeps controller acquisition at
0, ±4, ±7 and ±13 cm from the window with each of the four motion profiles.
See [lattice control evidence](audits/vr_lattice_controls_20260928.md).

Extrude length buttons follow the part lattice: ±7/±21 bp for honeycomb and
±8/±24 bp for square. Full `extrude_tour --validate` covers both lattices with
all four profiles. To demonstrate or validate only square extrusion:

```sh
uv run python -m tools.vr_workflows.extrude_tour --lattice square
uv run python -m tools.vr_workflows.extrude_tour --validate --lattice square
```

The square case creates a new square-lattice part through File → New, paints a
2×3 rectangle, extrudes 48 bp and checks equal perpendicular 2.25 nm grid pitches,
local view-volume rendering, and save/reload. It uses temporary workspace files.

Bending has a dedicated **Bend between two planes** authoring tour:
`just vr-bend-demo` or `just vr-bend-test`. The test restores the generated part
between all four controller profiles in one viewer session, checks both end grabs,
plane movement, wheels, desktop history, save/reload and Undo. See
[VR Bend](vr_bend.md#scrywrite-test-and-guided-vr-tour) for evidence and prerequisites.
