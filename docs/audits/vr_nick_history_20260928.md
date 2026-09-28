# VR Nick, Undo and Redo — 2026-09-28

All radius-wheel sectors are active. Nick replaces both controller selection
spheres with scissors at their usual selection-volume centers. Analog pressure
closes the blades and brightens a spatial halo on the candidate backbone bond.
The ordinary trigger click threshold (0.88, release hysteresis 0.60) creates one
nick via the desktop backend. Partial pulls and empty clicks do not edit. A held
trigger across the scene refresh does not repeat the cut.

Undo/Redo use desktop design history, cancel an active move preview, serialize
with wheel mutations, and refresh native geometry on success. Versioned catalogs
reject stale requests and the browser deduplicates journal events. Nick targets
ordered backbone neighbors; synthetic residues, individual loop-copy bonds and
ambiguous core coordinates are excluded from the coordinate-based API.
Wheel edits and end-resize commits also exclude each other while awaiting their
backend responses.

## Evidence

- Native build succeeded. Six focused native tests passed, including scissors
  closure, nick acquisition, click/held behavior, disabled input and history
  serialization, plus existing end-resize and interaction tests.
- Frontend coordinator/session tests: **47 passed**, including reverse-strand
  ordering, loop-copy exclusions, stale/assembly refusal and deduplication of all
  four wheel actions across the existing representation matrix.
- Backend protocol/routes/tours: **79 passed**; three additional full event-envelope
  cases also passed after the live protocol correction below.
- Browser smoke: the Nick demo and validation entries are visible in Authoring.
- ScryWrite transport suite: **25 passed**, including analog-pressure bounds and
  the native sequenced command handler. This harness is not headset evidence.
- Final physical OpenXR runtime with synthetic controllers: **4/4 profiles**
  (`steady_fast`, `steady_deliberate`, `variable_fast`, `variable_deliberate`).
  Each selects Nick through the actual wheel volumes, tests an empty click,
  captures pressure 0 / 0.45 / 0.8 without mutation, clicks to nick once, holds
  through refresh, then physically selects wheel Undo and Redo. Backend strand
  snapshots match the exact pre-nick and post-nick states after history actions.
- All 12 preview captures passed projected scissors-blade and bond-glow pixel
  checks in both submitted eyes and the actual native mirror buffer. Offscreen
  negative controls failed as expected. Open and nearly closed mirror frames
  were also visually inspected. Final motion runs required no acquisition retries.

Final evidence: `.development-artifacts/vr-nick/145d008fa4/result.json` and
`end/<profile>/.../{nick,undo,redo}/`. Captures, frame state, pixel reports,
reach traces and desktop snapshots are retained. Temporary documents and native
viewers were removed on exit.

Reproduce through Debug → VR Tours & Tests → Tools · Authoring → **Nick with
scissors, Undo and Redo**, or `uv run python -m tools.vr_workflows.nick_tour --validate`.

## Retained failure and limits

Initial campaign `255e9ec137` passed scissors/glow rendering but timed out waiting
for the cut: Nick published a `bond` selection level, which the existing event
envelope rejects. Nick now uses the supported `base` selection level while owning
its independent bond targeting. Added full-envelope regression cases cover the
actual transport. Motion profiles, selection radius and pixel thresholds were
unchanged for the passing campaign. Ordinary grip framing places the fixture in
the tracked view before measured reaches.

This campaign covers a small natural-pose design with the right controller;
native logic also accepts the left controller. Expanded, large/occluded designs,
human comfort and through-lens legibility still require broader observation.
Mirror evidence is the actual render buffer, not an OS desktop-window screenshot.
The earlier reported apparent base motion was explicitly deferred by the user
and is not claimed resolved by these checks.
