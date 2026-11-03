# VR Copy and Paste

Hold the right touchpad, move the thumb to **COPY**, then release. Copy snapshots
all currently selected supported elements, leaving the originals unchanged. A
mint wire preview follows the right hand's translation and rotation. Hold the
same pad, choose **PASTE**, and release to place the copy at the displayed pose.
Paste creates one undoable history entry. The preview stays fixed while saving,
clears on success, and remains available after a rejected paste. A saved edit is
not duplicated if its subsequent browser/VR refresh fails.

The six wheel sectors, counterclockwise from the right, are Ligate, Nick, Undo,
Redo, Copy, Paste. Tool-specific Bend/Sweep wheels retain their two actions.

Copy uses an immutable browser snapshot validated against the native action-time
owner tokens. Changing selection later cannot retarget the paste. A new document
or VR session clears the clipboard. Native preview geometry is bounded to 8,192
sampled segments; hand motion changes only its placement matrix.

All canonical selection types resolve to an immutable copy scope. Explicit
strands copy their domains; explicit clusters copy their selected membership.
Base/end picks copy the minimum owning domain, including a selected loop copy. Bonds copy the domains owning
their two endpoints; crossovers and forced ligations copy their endpoint domains.
Extensions carry their terminal owning domain and the extension; overhangs copy
their backing domain. A base on a real linker bridge copies its bridge domain,
without adjacent complement domains. Multiple picks form a union, with no duplicate DNA. Gaps
between selected domains become separate fragments rather than new connections.
Proteins and nanoparticles retain their owned DNA and receive the same rigid pose.

Copy validation supplies the preview for that resolved scope, independently of
the current display representation. DNA uses sparse backbone strokes and rigid
elements use bounding outlines. The preview appears after validation and stays
anchored to the right hand until Paste succeeds. Assembly instances are not yet
supported. Changing scene scale between Copy and Paste is rejected. Saved pose
metadata preserves displayed DNA placement without baking simulation coordinates
into topology.

## Validation

**Debug → VR Tours & Tests → Controls & layout → Right touchpad · Copy, hand
preview & Paste** runs the isolated browser-authoritative workflow. Its fixtures
cover two of three clusters, overlapping base/bond/extension picks, and proteins
plus nanoparticles. Each checks stereo preview pixels, moves and turns the
right hand through the standard human-motion driver, pastes, and checks Undo.
`--validate` runs steady_fast first and all four motion presets. The test uses a
normal bimanual grip to shrink the presentation for observation; it does not
alter production geometry, hit targets, or preset noise. Stereo captures are
followed by a half-second settle outside measured gestures to keep diagnostic
readback work out of thumb-playback timing. Runtime sidecars and sockets live in
a private Archive temporary directory that is removed even after a failed run.

```sh
python -m tools.vr_workflows.clipboard_tour --validate
```

Native scene export includes selectable protein traces and nanoparticle cores,
so committed rigid copies remain visible after the preview clears. The rigid
workflow checks added gold-core pixels in both eyes at the placement region.

Unit coverage: `tests/test_vr_clipboard.py`, `tests/test_element_copy.py`,
`frontend/src/scene/vr_clipboard.test.js`, and native `nadoc-vr-clipboard` and
`nadoc-vr-selection-wheel`. Retained evidence and failed attempts belong under
`.development-artifacts/vr-clipboard-all-20261016/app-visible/` (expanded final
campaign) and `.development-artifacts/vr-clipboard-20261016/` (initial cluster
campaign). Stereo application images do not
establish through-lens comfort or physical haptic feel.
