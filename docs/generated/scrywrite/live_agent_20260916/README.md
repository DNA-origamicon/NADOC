# Vive live-agent and object-ID validation — 2026-09-16

Passed on the physical Vive mounted on the dummy, using the existing SteamVR/X11
direct-mode path. No runtime/display settings were changed. SteamVR was initially
stopped and was started through NADOC's existing `/api/vr/runtime/start` endpoint.
Fresh compositor logs recorded `Acquired xlib display!`, `Direct mode: enabled`,
`Headset is using direct mode`, and `Startup Complete`.

The standalone viewer used `scrywrite_chiral_perspective.nadocvr`, live `control`
mode, physical left-eye mirror, and the existing stable-tracking scene placement
(front, mirror eye, 1.30 m, scale 2). This was a diagnostic fixture, not a browser
document or an authoritative editing transaction. All automated hand inputs were
released after the checks; one diagnostic viewer remained running.

Verified through the live Python bridge and real viewer input handlers:

- Runtime connected, focused, and fully tracked (`view_state_flags=15`).
- Advancing frames and successful submitted stereo captures at 1852 × 2056 per eye.
- Extrude activation, independent cell hover, one-cell painting and erasing.
- Three honeycomb wheel detents (+21 bp), without painting the lattice.
- A 0.10 m panel drag through actual grip input, then grip release.
- Lattice Exit cancellation and neutral controller release.
- Same-pass object IDs, with stable primitive identities across captures and zero
  IDs at every final overlay-class pixel.

The panel placement for the final run was derived from the captured physical eye
pose; the physical headset pose itself was never moved or substituted. Both model
and tool panels are visible in the actual submitted eye images:

[Left eye](left.png) · [Right eye](right.png)

| Capture | Frame | Left identified pixels | Right identified pixels | Left / right overlay pixels |
|---|---:|---:|---:|---:|
| Baseline | 13146 | 92,873 | 88,280 | 0 / 0 |
| Painted cell, panels visible | 13214 | 65,116 | 64,544 | 195,696 / 194,124 |
| Cancelled, inputs released | 13399 | 92,901 | 88,330 | 0 / 0 |

Minor baseline/final pixel differences are expected from physical tracking noise.
The baseline contains 15 visible primitive IDs in the left eye and 16 in the right;
the panel-covered capture contains 9 in each. All IDs resolve in the capture table,
and repeated primitive identities keep the same ID. This older diagnostic fixture
has no canonical owner aliases; their mapping is separately verified by the real-GL
regression using a known canonical owner.

[Validation JSON](validation.json) records counts, mappings, raw artifact paths and
SHA-256 hashes. [Painted-frame metadata](painted-evidence.json) records eye poses,
FOV, frame, session and interaction state. Raw color/depth/classes/IDs, the exact
validation scripts, viewer logs and command traces are retained under
`/tmp/nadoc-scrywrite-physical-20260916/` and are ephemeral. The live endpoint for
this standalone run is `/tmp/nadoc-scrywrite-physical-20260916/viewer.sock`; pass it
to the MCP bridge with `--socket` instead of backend-state discovery.

Regression validation: all 33 native tests passed, including real OpenGL primitive
identity/occlusion checks; 72 focused Python tests passed. The GL regression also
checks sphere discard, canonical owner lookup, style-switch identity persistence,
glow exclusion and production overlay masking. It skips explicitly if no usable
GL display/context exists.

These results establish the physical-runtime submitted-image path and live agent
interaction. They do not establish compositor panel scanout, human comfort or
legibility through the lenses, radial-menu acquisition, or browser-authoritative
Extrude commit/undo. Painted-footprint commit remains unsupported.
