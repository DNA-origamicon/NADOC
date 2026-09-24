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
